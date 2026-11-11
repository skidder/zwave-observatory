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
    return {"controller": ctrl, "jam_share": jam,
            "controller_problems": rank_problems(detect_controller_problems(jam))}


@api.get("/nodes")
async def nodes(request: Request) -> list[dict[str, Any]]:
    st = _state(request)
    if not st.nodes:
        try:
            await st.refresh()
        except Exception as e:
            raise HTTPException(503, f"cannot reach zwave-js-server: {e}")
    return st.nodes


@api.get("/nodes/{node_id}")
async def node_detail(node_id: int, request: Request) -> dict[str, Any]:
    st = _state(request)
    n = st.nodes_by_id.get(node_id)
    if n is None:
        raise HTTPException(404, f"node {node_id} not found")
    return n


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


# ---- problems / score ----
@api.get("/problems")
async def problems(request: Request) -> list[dict[str, Any]]:
    return _state(request).get_problems()


@api.get("/score")
async def score(request: Request) -> dict[str, Any]:
    return _state(request).get_score()


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
@api.websocket("/ws/live")
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


@api.get("/advisor/latest")
async def advisor_latest(request: Request) -> dict[str, Any]:
    r = _db(request).latest_report()
    if r is None:
        raise HTTPException(404, "no advisor reports yet")
    return r


@api.get("/advisor/history")
async def advisor_history(request: Request, limit: int = 50) -> list[dict[str, Any]]:
    return _db(request).report_history(limit)


@api.get("/advisor/ledger")
async def advisor_ledger(request: Request, days: int = 7) -> list[dict[str, Any]]:
    return _db(request).get_ledger(days)
