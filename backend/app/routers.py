"""HTTP + WS routers. Secrets never returned by any endpoint."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from .advisor import Advisor, LLMError, build_context_packet, validate_action
from .config import get_config
from .problems import detect_controller_problems, rank_problems
from .scoring import compute_node_score

api = APIRouter(prefix="/api")


def _state(request: Request):
    return request.app.state.state


def _db(request: Request):
    return request.app.state.db


# ---- basics ----
@api.get("/version")
async def version(request: Request) -> dict[str, Any]:
    return {"app": "zwave-observatory", "version": "0.1.0", "port": get_config().port}


@api.get("/controller")
async def controller(request: Request) -> dict[str, Any]:
    st = _state(request)
    ctrl = next((n for n in st.nodes if n.get("is_controller_node")), None)
    jam = st.jam_share
    status = (ctrl or {}).get("status") or "unknown"
    if status in ("dead", "unavailable"):
        fe_status = "offline"
    elif status in ("asleep", "unknown"):
        fe_status = "degraded"
    else:
        fe_status = "online"
    return {"status": fe_status,
            "jam_share_pct": round(jam * 100),
            "frames_per_day": 0, "dropped_per_day": 0,
            "collisions_per_day": 0, "bg_rssi": {}}


def _fe_node(n: dict[str, Any]) -> dict[str, Any]:
    """Map a backend node to the frontend ZwaveNode contract."""
    st = n.get("statistics") or {}
    hs = n.get("health_score") or {}
    status = (n.get("status") or "unknown").lower()
    vals = n.get("values") or []
    params = []
    for v in vals:
        if "config" in str((v.get("commandClass") or "")).lower() or \
                v.get("commandClass") == 112:
            params.append({
                "id": v.get("property"),
                "name": v.get("propertyName") or v.get("property"),
                "value": v.get("value"),
            })
    return {
        "id": n.get("node_id"),
        "name": n.get("name"),
        "loc": n.get("location"),
        "is_controller": bool(n.get("is_controller_node")),
        "power": "battery" if (n.get("power_source") == "battery") else "mains",
        "sleeping": status in ("asleep",),
        "dead": status in ("dead", "unavailable"),
        "grade": hs.get("grade") or "F",
        "stats": {
            "tx": st.get("commands_tx", 0),
            "rx": st.get("commands_rx", 0),
            "drops": (st.get("commands_dropped_tx", 0)
                      + st.get("commands_dropped_rx", 0)),
            "timeouts": st.get("timeout_response", 0),
            "rtt_ms": st.get("rtt") or 0,
            "rssi": st.get("rssi") if st.get("rssi") is not None else 0,
            "snr": st.get("snr") if st.get("snr") is not None else 0,
        },
        "routes": {
            "direct": not (n.get("routes") or {}).get("lwr"),
            "repeaters": [r.get("nodeId") for r in
                          [(n.get("routes") or {}).get("lwr") or {},
                           (n.get("routes") or {}).get("nlwr") or {}]
                          if isinstance(r, dict) and r.get("nodeId")],
        },
        "neighbors": n.get("neighbors") or [],
        "lwr_rssi": (n.get("statistics") or {}).get("lwr_rssi"),
        "nlwr_rssi": None,
        "ha_entities": [
            {"entity_id": e.get("entity_id"), "state": "", "name": e.get("name")}
            for e in n.get("entities") or []],
        "params": params,
        "problems": n.get("problems") or [],
        "last_seen": n.get("last_seen"),
    }


def _fe_mesh_node(n: dict[str, Any]) -> dict[str, Any]:
    hs = n.get("health_score") or {}
    status = (n.get("status") or "unknown").lower()
    return {
        "id": n.get("node_id"),
        "label": n.get("name") or f"Node {n.get('node_id')}",
        "is_controller": bool(n.get("is_controller_node")),
        "power": "battery" if (n.get("power_source") == "battery") else "mains",
        "grade": hs.get("grade") or "F",
        "sleeping": status == "asleep",
        "dead": status in ("dead", "unavailable"),
        "problems": len(n.get("problems") or []),
    }


@api.get("/nodes")
async def nodes(request: Request) -> list[dict[str, Any]]:
    st = _state(request)
    if not st.nodes:
        try:
            await st.refresh()
        except Exception as e:
            raise HTTPException(503, f"cannot reach zwave-js-server: {e}")
    return [_fe_node(n) for n in st.nodes]


@api.get("/nodes/{node_id}")
async def node_detail(node_id: int, request: Request) -> dict[str, Any]:
    st = _state(request)
    n = st.nodes_by_id.get(node_id)
    if n is None:
        raise HTTPException(404, f"node {node_id} not found")
    return _fe_node(n)


# ---- actions ----
@api.post("/nodes/{node_id}/ping")
async def node_ping(node_id: int, request: Request) -> dict[str, Any]:
    return await _run_action(request, "ping", node_id)


@api.post("/nodes/{node_id}/refresh")
async def node_refresh(node_id: int, request: Request) -> dict[str, Any]:
    return await _run_action(request, "refresh_values", node_id)


@api.post("/nodes/{node_id}/heal")
async def node_heal(node_id: int, request: Request) -> dict[str, Any]:
    return await _run_action(request, "heal_node", node_id)


@api.post("/nodes/{node_id}/params")
async def node_params(node_id: int, request: Request) -> dict[str, Any]:
    body = await request.json()
    params = {"parameter": body.get("parameter"), "value": body.get("value")}
    if body.get("value_size"):
        params["value_size"] = body["value_size"]
    return await _run_action(request, "set_config_parameter", node_id, params)


async def _run_action(request: Request, action: str, node_id: int,
                      params: dict[str, Any] | None = None) -> dict[str, Any]:
    st = _state(request)
    if node_id not in st.nodes_by_id:
        raise HTTPException(404, f"node {node_id} not found")
    try:
        result = await st.actions.run_action(action, node_id, params)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    except Exception as e:
        raise HTTPException(502, f"action failed: {e}")
    st.broadcast({"type": "action_result", "action": action, "node_id": node_id})
    return result


@api.get("/mesh")
async def mesh(request: Request) -> dict[str, Any]:
    st = _state(request)
    if not st.nodes:
        try:
            await st.refresh()
        except Exception as e:
            raise HTTPException(503, f"cannot reach zwave-js-server: {e}")
    nodes = [_fe_mesh_node(n) for n in st.nodes]
    edges = []
    for n in st.nodes:
        nid = n["node_id"]
        seen: set[int] = set()
        for target in n.get("neighbors") or []:
            if isinstance(target, int) and target != nid and target not in seen:
                seen.add(target)
                edges.append({"source": nid, "target": target, "kind": "neighbor"})
        routes = n.get("routes") or {}
        for kind in ("lwr", "nlwr"):
            r = routes.get(kind)
            if r and isinstance(r.get("nodeId"), int):
                edges.append({"source": nid, "target": r["nodeId"], "kind": kind,
                              "rssi": r.get("rssi")})
    return {"nodes": nodes, "edges": edges,
            "routes_as_of": (st.last_refresh_iso if hasattr(st, "last_refresh_iso")
                             else None) or _iso_now()}


def _iso_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# ---- problems / score ----
@api.get("/problems")
async def problems(request: Request) -> list[dict[str, Any]]:
    return _state(request).get_problems()


@api.get("/score")
async def score(request: Request) -> dict[str, Any]:
    st = _state(request)
    s = st.get_score()
    net = s.get("network") or {}
    total = net.get("total")
    # Frontend contract: {score 0-100, grade, penalties, history}
    history = [
        {"ts": row["ts_iso"] if "ts_iso" in row else str(row.get("ts", "")),
         "value": round((row.get("total") or 0) * 100)}
        for row in st.db.score_history(days=14)
    ] if hasattr(st.db, "score_history") else []
    return {
        "score": round((total or 0) * 100),
        "grade": net.get("grade") or "F",
        "penalties": (net.get("penalties")
                      or [p for v in (s.get("nodes") or {}).values()
                          for p in []]),
        "history": history,
    }


# ---- history ----
@api.get("/history/frames")
async def history_frames(request: Request, days: int = 7) -> dict[str, Any]:
    st = _state(request)
    if not st.influx:
        return {"data": [], "error": "influx not configured"}
    try:
        return {"data": await st.influx.query(
            f'from(bucket:"zwave") |> range(start: -{days}d) '
            f'|> filter(fn:(r) => r._measurement == "zwave_frames")')}
    except Exception as e:
        raise HTTPException(502, str(e))


@api.get("/history/rssi")
async def history_rssi(request: Request, days: int = 7) -> dict[str, Any]:
    st = _state(request)
    if not st.influx:
        return {"data": [], "error": "influx not configured"}
    try:
        return {"data": await st.influx.query(
            f'from(bucket:"zwave") |> range(start: -{days}d) '
            f'|> filter(fn:(r) => r._measurement == "zwave_rssi")')}
    except Exception as e:
        raise HTTPException(502, str(e))


@api.get("/history/controller")
async def history_controller(request: Request, days: int = 7) -> dict[str, Any]:
    st = _state(request)
    if not st.influx:
        return {"data": [], "error": "influx not configured"}
    try:
        return {"data": await st.influx.controller_history(days)}
    except Exception as e:
        raise HTTPException(502, str(e))


@api.get("/history/drops")
async def history_drops(request: Request, days: int = 7) -> dict[str, Any]:
    st = _state(request)
    if not st.influx:
        return {"data": [], "error": "influx not configured"}
    try:
        return {"data": await st.influx.query(
            f'from(bucket:"zwave") |> range(start: -{days}d) '
            f'|> filter(fn:(r) => r._measurement == "zwave_drops")')}
    except Exception as e:
        raise HTTPException(502, str(e))


# ---- WS live ----
# Registered on its own router (no /api prefix): the SPA dials /ws/live at
# the host root, matching the documented contract.
ws_router = APIRouter()


@ws_router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    st = websocket.app.state.state
    st._ws_clients.append(websocket)
    try:
        await websocket.send_json({"type": "snapshot", "nodes": st.nodes,
                                   "score": st.get_score() if st.nodes else None})
        while True:
            await websocket.receive_text()  # keepalive / pings
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in st._ws_clients:
            st._ws_clients.remove(websocket)


# ---- audit / dismiss ----
@api.get("/audit")
async def audit(request: Request, limit: int = 200) -> list[dict[str, Any]]:
    return _db(request).get_audit(limit)


@api.post("/problems/{problem_id}/dismiss")
async def dismiss(problem_id: str, request: Request) -> dict[str, Any]:
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    _db(request).dismiss(problem_id, body.get("node_id"),
                         body.get("reason"), body.get("until"))
    return {"ok": True, "problem_key": problem_id}


# ---- setup wizard ----
@api.get("/setup/status")
async def setup_status(request: Request) -> dict[str, Any]:
    from .wizard import setup_status as _status
    return _status(get_config())


@api.post("/setup/test/{step}")
async def setup_test(step: str, request: Request) -> dict[str, Any]:
    from .wizard import test_step
    try:
        values = await request.json()
    except Exception:
        values = {}
    return await test_step(step, values)


@api.post("/setup/complete")
async def setup_complete(request: Request) -> dict[str, Any]:
    from .wizard import complete_setup
    try:
        values = await request.json()
    except Exception:
        raise HTTPException(400, "JSON body required")
    return complete_setup(values)


# ---- advisor ----
@api.post("/advisor/analyze")
async def advisor_analyze(request: Request) -> dict[str, Any]:
    st = _state(request)
    advisor: Advisor = request.app.state.advisor
    if not st.nodes:
        try:
            await st.refresh()
        except Exception as e:
            raise HTTPException(503, f"cannot reach zwave-js-server: {e}")
    try:
        await st.update_chatty_rates()
    except Exception:
        pass
    packet = build_context_packet(st.nodes, st.get_problems(), st.network_score,
                                  st.db.get_ledger(days=7),
                                  sorted(st.db.active_dismissals()))
    try:
        out = await advisor.analyze(packet)
    except LLMError as e:
        raise HTTPException(429 if "rate limited" in str(e) or "cap" in str(e) else 500, str(e))
    # validate + append proposed actions to ledger as pending
    confirmed = st.db.confirmed_actions(days=14)
    for rec in out["report"].get("recommended_actions", []):
        errs = validate_action(rec, st.nodes_by_id, st.db.open_pending_actions(),
                               confirmed)
        st.db.append_ledger_action(out["report_id"], rec["action"], rec.get("node_id"),
                                   rec.get("parameters"), rec.get("problem_refs", []),
                                   rec.get("explanation"),
                                   verification_status="pending" if not errs else "inconclusive")
    st.broadcast({"type": "advisor_report", "report_id": out["report_id"]})
    return out


@api.post("/advisor/investigate")
async def advisor_investigate(request: Request) -> dict[str, Any]:
    st = _state(request)
    advisor: Advisor = request.app.state.advisor
    try:
        question = (await request.json()).get("question", "Investigate the current network problems.")
    except Exception:
        question = "Investigate the current network problems."

    async def get_node(node_id: int) -> Any:
        n = st.nodes_by_id.get(node_id)
        return n or {"error": f"node {node_id} not found"}

    async def get_history(node_id: int, days: int = 7) -> Any:
        return await st.node_history(node_id, days)

    async def get_problems() -> Any:
        return st.get_problems()

    async def get_automation_refs() -> Any:
        try:
            cfg = get_config()
            states = await st.ha.get_states()
            automs = [s for s in states if s.get("entity_id", "").startswith("automation.")]
            refs: list[str] = []
            for a in automs:
                refs.extend((a.get("attributes", {}).get("entity_id") or []))
            return {"entity_refs": refs}
        except Exception as e:
            return {"entity_refs": [], "error": str(e)}

    async def ping(node_id: int) -> Any:
        try:
            return await st.actions.run_action("ping", node_id, actor="advisor")
        except Exception as e:
            return {"error": str(e)}

    advisor.read_tools = {"get_node": get_node, "get_history": get_history,
                          "get_problems": get_problems,
                          "get_automation_refs": get_automation_refs,
                          "ping": ping}
    try:
        return await advisor.investigate(question)
    except LLMError as e:
        raise HTTPException(500, str(e))


def _fe_report(row: dict[str, Any]) -> dict[str, Any]:
    """Map an advisor_reports DB row to the frontend AdvisorReport contract."""
    rep = row.get("report") or {}
    ts = row.get("ts")
    if isinstance(ts, (int, float)):
        from datetime import datetime, timezone
        ts_iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    elif ts:
        ts_iso = str(ts)
    else:
        ts_iso = _iso_now()
    recs = []
    actions = rep.get("recommended_actions") or []
    for i, a in enumerate(actions):
        a = a if isinstance(a, dict) else {}
        recs.append({
            "id": f"r{row.get('id')}-{i}",
            "created": ts_iso,
            "diagnosis": a.get("explanation") or rep.get("summary") or "",
            "confidence": 0.5,
            "evidence_links": [],
            "actions": [{
                "id": f"a{row.get('id')}-{i}",
                "description": a.get("action") or "unknown",
                "kind": a.get("action") or "unknown",
                "validation": "pending",
            }],
            "verdict": "pending",
        })
    obs = "\n".join(f"- {o}" for o in rep.get("observations") or [])
    return {
        "id": row.get("id"),
        "run_at": ts_iso,
        "model": rep.get("model") or "",
        "tokens": {"input": row.get("tokens_in") or 0,
                   "output": row.get("tokens_out") or 0},
        "cost_usd": 0.0,
        "recommendations": recs,
        "markdown": "\n\n".join(x for x in (rep.get("summary"), obs) if x),
        "transcript": "",
    }


@api.get("/advisor/latest")
async def advisor_latest(request: Request) -> dict[str, Any]:
    r = _db(request).latest_report()
    if r is None:
        raise HTTPException(404, "no advisor reports yet")
    return _fe_report(r)


@api.get("/advisor/history")
async def advisor_history(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return [_fe_report(r) for r in _db(request).report_history(limit)]


@api.get("/advisor/ledger")
async def advisor_ledger(request: Request, days: int = 7) -> list[dict[str, Any]]:
    return _db(request).get_ledger(days)
