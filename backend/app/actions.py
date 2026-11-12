"""Node actions: ping/refresh_values/re_interview/heal_node/set_config_parameter/refresh_neighbors.

- At most 1 mutating action in flight (ping is non-mutating).
- Audit entries include params_before / params_after.
- Config parameter writes verify via readback.
- heal_node is per-node only (never network-wide); a heal schedules a re-read
  of node health after 10 minutes.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .config import get_config
from .db import Database
from .zwjs import ZwjsClient

MUTATING_ACTIONS = {"refresh_values", "re_interview", "heal_node",
                    "set_config_parameter", "refresh_neighbors"}
ALLOWED_ACTIONS = {"ping"} | MUTATING_ACTIONS

_READABLE_CC = 112  # Configuration CC


class ActionManager:
    def __init__(self, db: Database, emit=None):
        self.db = db
        self.emit = emit or (lambda *a, **k: None)
        self._mutating_lock = asyncio.Lock()
        self._in_flight: str | None = None

    def in_flight(self) -> str | None:
        return self._in_flight

    def _client(self) -> ZwjsClient:
        cfg = get_config()
        return ZwjsClient(cfg.zwjs_ws_url, cfg.zwjs_token)

    async def run_action(self, action: str, node_id: int,
                         params: dict[str, Any] | None = None,
                         actor: str = "user") -> dict[str, Any]:
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"action not allowed: {action}")
        params = params or {}

        # per-node heal only — never network-wide
        if action == "heal_node" and (params.get("network_wide") or params.get("all")):
            raise ValueError("network-wide heal is not allowed; heal per node only")

        mutating = action in MUTATING_ACTIONS
        if mutating:
            if self._in_flight is not None:
                raise RuntimeError(f"a mutating action is already in flight: {self._in_flight}")
            acquired = self._mutating_lock.locked()
            if acquired:
                raise RuntimeError("a mutating action is already in flight")
        client = self._client()
        audit_id = self.db.add_audit(
            actor=actor, action=action, node_id=node_id,
            params_before=params, result={"status": "started"}, source="api")
        try:
            if mutating:
                async with self._mutating_lock:
                    self._in_flight = action
                    try:
                        result = await self._execute(client, action, node_id, params)
                    finally:
                        self._in_flight = None
            else:
                result = await self._execute(client, action, node_id, params)
        except Exception as e:
            self.emit({"type": "action_event", "ts": time.time(), "action": action,
                       "node_id": node_id, "message": f"failed: {e}", "level": "error"})
            self.db.add_audit(actor=actor, action=action, node_id=node_id,
                              params_before=params, result={"status": "error", "error": str(e)},
                              source="api")
            raise
        self.db.add_audit(actor=actor, action=action, node_id=node_id,
                          params_before=params, params_after=result.get("params_after"),
                          result={"status": "ok", "result": result.get("result")},
                          source="api")
        self.emit({"type": "action_event", "ts": time.time(), "action": action,
                   "node_id": node_id, "message": "completed", "level": "ok"})
        if action == "heal_node":
            self._schedule_post_heal_reread(node_id)
        return result

    async def _execute(self, client: ZwjsClient, action: str, node_id: int,
                       params: dict[str, Any]) -> dict[str, Any]:
        def ev(message: str, **extra: Any) -> None:
            self.emit({"type": "action_event", "ts": time.time(),
                       "action": action, "node_id": node_id, "message": message, **extra})

        ev("started")
        if action == "ping":
            ev("pinging node over the Z-Wave mesh...")
            r = await client.ping_node(node_id)
            if isinstance(r, dict):
                reply = r.get("status", r)
            else:
                reply = r if r is not None else "no response payload (likely awake, no callback)"
            ev(f"ping replied: {reply}")
            return {"action": action, "node_id": node_id, "result": r}

        if action == "refresh_values":
            r = await client.refresh_values(node_id)
            return {"action": action, "node_id": node_id, "result": r}

        if action == "re_interview":
            r = await client.refresh_info(node_id)
            return {"action": action, "node_id": node_id, "result": r}

        if action == "heal_node":
            r = await client.heal_node(node_id)
            return {"action": action, "node_id": node_id,
                    "result": r, "note": "health re-read scheduled in 10 minutes"}

        if action == "refresh_neighbors":
            r = await client.send_command("node_get_neighbours", nodeId=node_id)
            return {"action": action, "node_id": node_id, "result": r}

        if action == "set_config_parameter":
            param = int(params["parameter"])
            value = params["value"]
            ev("reading current value of parameter {p}...".format(p=param))
            before = await self._read_param(client, node_id, param)
            ev(f"current value: {before.get('value') if before else 'unknown'}")
            ev(f"writing parameter {param} = {value}...")
            await client.set_config_parameter(node_id, param, value,
                                              params.get("value_size"))
            await asyncio.sleep(0.5)
            ev(f"re-reading parameter {param} to verify...")
            after = await self._read_param(client, node_id, param)
            verified = after is not None and str(after.get("value")) == str(value)
            ev(f"readback value: {after.get('value') if after else 'unknown'} "
               f"({'verified' if verified else 'NOT verified'})")
            return {
                "action": action, "node_id": node_id,
                "parameter": param,
                "params_after": {"parameter": param, "value": after.get("value") if after else None},
                "result": {"verified": verified,
                           "before": before.get("value") if before else None,
                           "after": after.get("value") if after else None,
                           "readback": after},
            }
        raise ValueError(action)

    async def _read_param(self, client: ZwjsClient, node_id: int, param: int) -> Any:
        try:
            state = await client.get_state()
            for n in state.get("nodes", []):
                if n.get("nodeId") != node_id:
                    continue
                for v in n.get("values", []):
                    if v.get("commandClass") == _READABLE_CC and v.get("property") == param:
                        return {"value": v.get("value")}
        except Exception:
            return None
        return None

    def _schedule_post_heal_reread(self, node_id: int) -> None:
        """Schedule a health re-read 10 minutes after a heal."""
        async def _later() -> None:
            await asyncio.sleep(600)
            try:
                state = await self._client().get_state()
                self.db.add_audit(actor="scheduler", action="post_heal_reread",
                                  node_id=node_id, result={"status": "ok"},
                                  source="scheduler")
                for n in state.get("nodes", []):
                    if n.get("nodeId") == node_id:
                        break
            except Exception:
                self.db.add_audit(actor="scheduler", action="post_heal_reread",
                                  node_id=node_id,
                                  result={"status": "error"}, source="scheduler")
        try:
            asyncio.get_running_loop().create_task(_later())
        except RuntimeError:
            pass
