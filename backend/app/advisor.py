"""Advisor: provider-agnostic LLM client (anthropic / openai / openai_compatible /
ollama), context packet builder, one-shot analyze, tool-loop investigate,
deterministic action validator."""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Awaitable, Callable

import httpx

from .db import Database

ACTIONS_ALLOWED = ["ping", "refresh_values", "re_interview", "heal_node",
                   "set_config_parameter", "refresh_neighbors"]

ANALYZE_SCHEMA = {
    "type": "object",
    "required": ["summary", "observations", "recommended_actions"],
    "properties": {
        "summary": {"type": "string"},
        "observations": {"type": "array", "items": {"type": "string"}},
        "recommended_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action", "node_id", "explanation"],
                "properties": {
                    "action": {"type": "string", "enum": ACTIONS_ALLOWED},
                    "node_id": {"type": "integer"},
                    "parameters": {"type": "object"},
                    "problem_refs": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                },
            },
        },
    },
}


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str | None,
                 base_url: str | None = None, max_tokens: int = 4096,
                 daily_cap: int = 200_000):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.max_tokens = max_tokens
        self.daily_cap = daily_cap
        self._tokens_used_today = 0

    def _check_cap(self, est_tokens: int) -> None:
        if self._tokens_used_today + est_tokens > self.daily_cap:
            raise LLMError("daily token cap exceeded")

    def _record(self, tin: int, tout: int) -> None:
        self._tokens_used_today += tin + tout

    async def chat(self, messages: list[dict[str, Any]],
                   system: str | None = None,
                   tools: list[dict[str, Any]] | None = None,
                   force_json: bool = False) -> dict[str, Any]:
        """Returns {'text': str, 'tool_calls': [...], 'tokens_in': int, 'tokens_out': int}."""
        est = sum(len(json.dumps(m)) // 3 for m in messages) + len(system or "") // 3 + self.max_tokens
        self._check_cap(est)
        if self.provider == "anthropic":
            return await self._chat_anthropic(messages, system, tools)
        if self.provider == "openai":
            return await self._chat_openai("https://api.openai.com/v1", messages, system, tools)
        if self.provider == "openai_compatible":
            return await self._chat_openai(self.base_url or "", messages, system, tools)
        if self.provider == "ollama":
            return await self._chat_ollama(messages, system)
        raise LLMError(f"unknown provider: {self.provider}")

    async def _chat_anthropic(self, messages: list[dict[str, Any]],
                              system: str | None, tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [{"role": m.get("role", "user"),
                          "content": m.get("content") if not isinstance(m.get("content"), dict)
                          else json.dumps(m["content"])}
                         for m in messages],
        }
        if system:
            body["system"] = system
        if tools:
            body["tools"] = [{"name": t["name"], "description": t.get("description", ""),
                              "input_schema": t.get("parameters", {})} for t in tools]
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post("https://api.anthropic.com/v1/messages",
                             headers={"x-api-key": self.api_key or "",
                                      "anthropic-version": "2023-06-01"},
                             json=body)
            r.raise_for_status()
            data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        tool_calls = [{"name": b["name"], "arguments": b.get("input", {})}
                      for b in data.get("content", []) if b.get("type") == "tool_use"]
        tin = data.get("usage", {}).get("input_tokens", 0)
        tout = data.get("usage", {}).get("output_tokens", 0)
        self._record(tin, tout)
        return {"text": text, "tool_calls": tool_calls, "tokens_in": tin, "tokens_out": tout}

    async def _chat_openai(self, base: str, messages: list[dict[str, Any]],
                           system: str | None, tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": m.get("role", "user"), "content": m.get("content")} for m in messages]
        body: dict[str, Any] = {"model": self.model, "messages": msgs,
                                "max_tokens": self.max_tokens}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"],
                                           "description": t.get("description", ""),
                                           "parameters": t.get("parameters", {})}} for t in tools]
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{base}/chat/completions",
                             headers={"Authorization": f"Bearer {self.api_key or ''}"},
                             json=body)
            r.raise_for_status()
            data = r.json()
        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        tool_calls = [{"name": tc["function"]["name"],
                       "arguments": json.loads(tc["function"].get("arguments") or "{}")}
                      for tc in msg.get("tool_calls", [])]
        usage = data.get("usage", {})
        self._record(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        return {"text": msg.get("content") or "", "tool_calls": tool_calls,
                "tokens_in": usage.get("prompt_tokens", 0),
                "tokens_out": usage.get("completion_tokens", 0)}

    async def _chat_ollama(self, messages: list[dict[str, Any]], system: str | None) -> dict[str, Any]:
        base = self.base_url or "http://localhost:11434"
        msgs = ([{"role": "system", "content": system}] if system else []) + \
               [{"role": m.get("role", "user"), "content": m.get("content")} for m in messages]
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{base}/api/chat",
                             json={"model": self.model, "messages": msgs, "stream": False})
            r.raise_for_status()
            data = r.json()
        text = data.get("message", {}).get("content", "")
        tin = data.get("prompt_eval_count", 0) or 0
        tout = data.get("eval_count", 0) or 0
        self._record(tin, tout)
        return {"text": text, "tool_calls": [], "tokens_in": tin, "tokens_out": tout}


# ---------------- context packet ----------------
def build_context_packet(nodes: list[dict[str, Any]], problems: list[dict[str, Any]],
                         network_score: dict[str, Any] | None,
                         past_actions: list[dict[str, Any]],
                         dismissals: list[str], max_tokens: int = 8000) -> str:
    """~6-8k token context packet. past_actions come from the ledger."""
    lines: list[str] = ["# Z-Wave Health Observatory context packet"]
    if network_score:
        lines.append(f"## Network score: {network_score.get('total')} ({network_score.get('grade')})")
        if network_score.get("note"):
            lines.append(f"note: {network_score['note']}")
    lines.append("## Problems (ranked)")
    for p in problems[:40]:
        lines.append(f"- [{p['severity']}] {p['type']} node={p.get('node_id')}: {p['message']}")
    lines.append("## Nodes")
    for n in nodes[:50]:
        stats = n.get("statistics") or {}
        hs = n.get("health_score") or {}
        lines.append(
            f"- id={n['node_id']} name={n.get('name')} status={n.get('status')} "
            f"power={n.get('power_source')} score={hs.get('total')}({hs.get('grade')}) "
            f"rx={stats.get('commands_rx')} dropped_rx={stats.get('commands_dropped_rx')} "
            f"timeouts={stats.get('timeout_response')} rssi={stats.get('rssi')} "
            f"last_seen={n.get('last_seen')} neighbors={n.get('neighbors')}")
    lines.append("## Past advisor actions (ledger, last 7 days)")
    for a in past_actions[:30]:
        lines.append(f"- id={a['id']} ts={a['ts']} action={a['action']} node={a.get('node_id')} "
                     f"params={a.get('params')} problem_refs={a.get('problem_refs')} "
                     f"verification={a.get('verification_status')}")
    if dismissals:
        lines.append("## Dismissed problems (do not re-recommend)")
        lines.extend(f"- {d}" for d in dismissals)
    lines.append("## Allowed actions")
    lines.extend(f"- {a}" for a in ACTIONS_ALLOWED)
    pkt = "\n".join(lines)
    # rough truncation to token budget (~4 chars/token)
    if len(pkt) > max_tokens * 4:
        pkt = pkt[: max_tokens * 4]
    return pkt


# ---------------- validator ----------------
def validate_action(rec: dict[str, Any], nodes_by_id: dict[int, dict[str, Any]],
                    open_pending: list[dict[str, Any]],
                    confirmed_recent: list[dict[str, Any]],
                    automation_refs: dict[str, list[str]] | None = None) -> list[str]:
    """Deterministic validation. Returns list of rejection reasons (empty = valid)."""
    errors: list[str] = []
    action = rec.get("action")
    node_id = rec.get("node_id")
    if action not in ACTIONS_ALLOWED:
        errors.append(f"action '{action}' not in allowed enum")
    if node_id not in nodes_by_id:
        errors.append(f"node_id {node_id} does not exist")
    # param range vs device metadata (configuration parameters in node values)
    params = rec.get("parameters") or {}
    if action == "set_config_parameter":
        node = nodes_by_id.get(node_id, {})
        param_num = params.get("parameter")
        value = params.get("value")
        found = False
        for v in node.get("values", []) or []:
            if v.get("commandClass") == 112 and v.get("property") == param_num:
                found = True
                meta = v.get("metadata") or {}
                vmin, vmax = meta.get("min"), meta.get("max")
                if value is not None:
                    if isinstance(value, (int, float)) and isinstance(vmin, (int, float)) \
                            and isinstance(vmax, (int, float)):
                        if not (vmin <= value <= vmax):
                            errors.append(
                                f"parameter {param_num} value {value} outside device metadata range {vmin}..{vmax}")
                states = meta.get("states")
                if states and isinstance(value, int) and value not in states:
                    errors.append(f"parameter {param_num} value {value} not in labeled states {list(states)}")
                break
        if node_id in nodes_by_id and not found:
            errors.append(f"parameter {param_num} not present in device metadata")

    # automation-reference guard: never touch things referenced by automations
    if automation_refs:
        refs = rec.get("problem_refs") or []
        for ref in refs:
            if ref in automation_refs.get("entity_refs", []):
                errors.append(f"problem ref {ref} is referenced by an automation; guard applies")

    # duplicate open pending ledger entry for same problem refs
    if not errors:
        new_refs = set(rec.get("problem_refs") or [])
        if new_refs:
            for pend in open_pending:
                if pend.get("action") == action and pend.get("node_id") == node_id:
                    if new_refs & set(pend.get("problem_refs") or []):
                        errors.append(
                            f"duplicates open pending ledger entry #{pend.get('id')} for same problem refs")
                        break
        # re-flagging confirmed_improvement within 14d without explanation
        if new_refs:
            for conf in confirmed_recent:
                if conf.get("action") == action and conf.get("node_id") == node_id:
                    if new_refs & set(conf.get("problem_refs") or []):
                        if not (rec.get("explanation") or "").strip():
                            errors.append(
                                f"re-flags problem confirmed improved (ledger #{conf.get('id')}) within 14 days without explanation")
                        break
    return errors


# ---------------- advisor service ----------------
class Advisor:
    def __init__(self, db: Database, llm: LLMClient,
                 read_tools: dict[str, Callable[..., Awaitable[Any]]] | None = None):
        self.db = db
        self.llm = llm
        self.read_tools = read_tools or {}
        self._last_analyze_ts: float = 0.0
        self.rate_limit_seconds = 600  # 1 per 10 min

    def check_rate_limit(self) -> None:
        if self._last_analyze_ts and time.time() - self._last_analyze_ts < self.rate_limit_seconds:
            raise LLMError("analyze rate limited: 1 per 10 minutes")

    # ---- one-shot analyze ----
    async def analyze(self, context_packet: str) -> dict[str, Any]:
        self.check_rate_limit()
        self._last_analyze_ts = time.time()
        system = (
            "You are a Z-Wave network health advisor. Return ONLY JSON matching this schema: "
            + json.dumps(ANALYZE_SCHEMA)
            + ". Every recommended action must cite problem_refs and include an explanation."
        )
        result = await self.llm.chat([{"role": "user", "content": context_packet}], system=system)
        parsed, err = _try_parse_json(result["text"])
        if err:
            # one retry with the error fed back
            retry = await self.llm.chat(
                [{"role": "user", "content": context_packet},
                 {"role": "assistant", "content": result["text"]},
                 {"role": "user", "content": f"Your JSON was invalid: {err}. Return corrected JSON only."}],
                system=system)
            result = retry
            parsed, err = _try_parse_json(retry["text"])
        if err:
            raise LLMError(f"advisor JSON failed validation after retry: {err}")
        report_id = self.db.add_report("analyze", parsed,
                                       result["tokens_in"], result["tokens_out"])
        return {"report_id": report_id, "report": parsed,
                "tokens_in": result["tokens_in"], "tokens_out": result["tokens_out"]}

    # ---- tool-loop investigate ----
    INVESTIGATE_TOOLS = [
        {"name": "get_node", "description": "Get full node details", "parameters": {
            "type": "object", "properties": {"node_id": {"type": "integer"}},
            "required": ["node_id"]}},
        {"name": "get_history", "description": "Get node frame/rssi history", "parameters": {
            "type": "object", "properties": {"node_id": {"type": "integer"}, "days": {"type": "integer"}},
            "required": ["node_id"]}},
        {"name": "get_problems", "description": "Get current ranked problems", "parameters": {
            "type": "object", "properties": {}}},
        {"name": "get_automation_refs", "description": "Get entities referenced by automations", "parameters": {
            "type": "object", "properties": {}}},
        {"name": "ping", "description": "Ping a node", "parameters": {
            "type": "object", "properties": {"node_id": {"type": "integer"}}, "required": ["node_id"]}},
    ]

    async def investigate(self, question: str, max_rounds: int = 6,
                          hard_timeout: float = 120.0) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        tool_trace: list[dict[str, Any]] = []
        start = time.time()
        try:
            return await asyncio.wait_for(
                self._investigate_loop(messages, tool_trace, max_rounds), timeout=hard_timeout)
        except asyncio.TimeoutError:
            return {"mode": "investigate", "summary": "investigation timed out at 120s",
                    "tool_trace": tool_trace, "timed_out": True}

    async def _investigate_loop(self, messages: list[dict[str, Any]],
                                tool_trace: list[dict[str, Any]],
                                max_rounds: int) -> dict[str, Any]:
        for _ in range(max_rounds):
            resp = await self.llm.chat(messages, tools=self.INVESTIGATE_TOOLS)
            if resp["tool_calls"]:
                messages.append({"role": "assistant",
                                 "content": resp["text"] or "",
                                 "tool_calls": resp["tool_calls"]})
                for tc in resp["tool_calls"]:
                    fn = self.read_tools.get(tc["name"])
                    if fn is None:
                        tool_res = {"error": f"tool '{tc['name']}' not available (read-only tools only)"}
                    else:
                        try:
                            tool_res = await fn(**tc["arguments"])
                        except Exception as e:
                            tool_res = {"error": str(e)}
                    tool_trace.append({"tool": tc["name"], "args": tc["arguments"], "result": tool_res})
                    messages.append({"role": "user", "tool_result": tool_res,
                                     "content": json.dumps(tool_res, default=str)[:4000]})
                continue
            parsed, err = _try_parse_json(resp["text"])
            if err:
                report_id = self.db.add_report("investigate", {"summary": resp["text"]},
                                               resp["tokens_in"], resp["tokens_out"])
                return {"report_id": report_id, "mode": "investigate",
                        "summary": resp["text"], "tool_trace": tool_trace}
            report_id = self.db.add_report("investigate", parsed,
                                           resp["tokens_in"], resp["tokens_out"])
            return {"report_id": report_id, "mode": "investigate",
                    "report": parsed, "tool_trace": tool_trace}
        return {"mode": "investigate", "summary": "max tool rounds reached",
                "tool_trace": tool_trace}


def _try_parse_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    if not text or not text.strip():
        return None, "empty response"
    m = re.search(r"\{.*\}", text, re.DOTALL)
    candidate = m.group(0) if m else text
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    # schema validation (minimal)
    missing = [k for k in ANALYZE_SCHEMA["required"] if k not in obj]
    if missing:
        return None, f"missing required keys: {missing}"
    if not isinstance(obj.get("observations", []), list):
        return None, "observations must be a list"
    if not isinstance(obj.get("recommended_actions", []), list):
        return None, "recommended_actions must be a list"
    for ra in obj.get("recommended_actions", []):
        if ra.get("action") not in ACTIONS_ALLOWED:
            return None, f"invalid action: {ra.get('action')}"
    return obj, None
