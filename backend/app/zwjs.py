"""zwave-js-server websocket client.

Connects, sends start_listening with a minSchemaVersion clamped to the
server's max, receives the full state snapshot, then streams events.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Callable

DEFAULT_MIN_SCHEMA = 0  # we advertise the lowest; the server replies with its max


class ZwjsError(RuntimeError):
    pass


# zwave-js-server node status enum -> name (values may arrive as int or str)
_NODE_STATUS = {0: "unknown", 1: "asleep", 2: "awake", 3: "dead", 4: "alive"}


def _status_name(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return _NODE_STATUS.get(v, str(v))
    s = str(v)
    return _NODE_STATUS.get(int(s)) if s.isdigit() else s.lower()


class ZwjsClient:
    def __init__(self, ws_url: str, token: str | None = None):
        self.ws_url = ws_url
        self.token = token
        self._msg_id = 0
        self._state: dict[str, Any] | None = None
        self._schema_version: int | None = None
        self._listeners: list[Callable[[dict[str, Any]], Any]] = []

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def _auth_payload(self) -> dict[str, Any]:
        p: dict[str, Any] = {}
        if self.token:
            p["securityToken"] = self.token  # zwave-js-server auth
        return p

    async def negotiate_schema(self, ws: Any) -> tuple[int, dict[str, Any]]:
        """Send start_listening; clamp our minSchemaVersion to server max.
        Returns (schema_version, initial_state)."""
        import websockets  # noqa: F401  (ensures availability for callers)

        hello_raw = await asyncio.wait_for(ws.recv(), timeout=15)
        hello = json.loads(hello_raw)
        if hello.get("type") == "version":
            server_max = int(hello.get("maxSchemaVersion", 0))
        elif hello.get("type") == "error":
            raise ZwjsError(f"server error on connect: {hello}")
        else:
            # some servers send version info inline
            server_max = int(hello.get("maxSchemaVersion", 0) or 0)

        # Clamp: our minimum must not exceed what the server supports.
        our_min = min(DEFAULT_MIN_SCHEMA, server_max) if server_max else DEFAULT_MIN_SCHEMA
        await ws.send(json.dumps({
            "messageId": "start-listening",
            "command": "start_listening",
            "minSchemaVersion": our_min,
            **self._auth_payload(),
        }))

        # first response: result with state
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        msg = json.loads(raw)
        if msg.get("type") == "error":
            raise ZwjsError(f"start_listening failed: {msg}")
        if msg.get("type") != "result":
            raise ZwjsError(f"expected result, got {msg.get('type')}")
        state = msg.get("result", {}).get("state") or {}
        schema = int(msg.get("schemaVersion") or state.get("schemaVersion") or our_min)
        return schema, state

    async def get_state(self) -> dict[str, Any]:
        """One-shot connect, start_listening, return state, disconnect."""
        import websockets
        extra = {"extra_headers": {"Authorization": f"Bearer {self.token}"}} if self.token else {}
        async with websockets.connect(self.ws_url, max_size=2**26, **extra) as ws:
            _, state = await self.negotiate_schema(ws)
            self._state = state
            return state

    async def listen(self) -> AsyncIterator[dict[str, Any]]:
        """Yield events from a start_listening session after the initial result."""
        import websockets
        extra = {"extra_headers": {"Authorization": f"Bearer {self.token}"}} if self.token else {}
        async with websockets.connect(self.ws_url, max_size=2**26, **extra) as ws:
            schema, state = await self.negotiate_schema(ws)
            self._schema_version = schema
            self._state = state
            yield {"type": "initial_state", "state": state, "schemaVersion": schema}
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=120)
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    yield msg
                elif msg.get("type") == "error":
                    yield msg

    # ---- helpers to shape the state into observatory nodes ----
    @staticmethod
    def extract_nodes(state: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = []
        for n in state.get("nodes", []):
            nodes.append(ZwjsClient.shape_node(n))
        return nodes

    @staticmethod
    def shape_node(n: dict[str, Any]) -> dict[str, Any]:
        stats = n.get("statistics") or {}
        lwr = n.get("lwr") or n.get("lowestRSSI") or {}
        return {
            "node_id": n.get("nodeId"),
            "name": n.get("name") or n.get("deviceClass", {}).get("label") or f"Node {n.get('nodeId')}",
            "location": n.get("location"),
            "device_id": n.get("deviceConfig", {}).get("deviceId") or n.get("hexNodeId"),
            "manufacturer": n.get("manufacturer"),
            "product": n.get("productLabel") or n.get("productDescription"),
            "protocol": {
                "version": n.get("protocolVersion"),
                "data_rate": n.get("maxDataRate"),
                "role": n.get("deviceRole") or n.get("deviceClass", {}).get("role"),
            },
            "status": _status_name(n.get("status")),
            "ready": bool(n.get("ready")),
            "is_controller_node": bool(n.get("isControllerNode")),
            "neighbors": n.get("neighbors") or [],
            "routes": {
                "lwr": n.get("lwr") or None,
                "nlwr": n.get("nlwr") or None,
                "custom": n.get("customSUCReturnRoutes") or None,
            },
            "statistics": {
                "commands_tx": stats.get("commandsTX", 0),
                "commands_rx": stats.get("commandsRX", 0),
                "commands_dropped_tx": stats.get("commandsDroppedTX", 0),
                "commands_dropped_rx": stats.get("commandsDroppedRX", 0),
                "timeout_response": stats.get("timeoutResponse", 0),
                "rtt": stats.get("rtt"),
                "rssi": stats.get("rssi"),
                "lwr_rssi": lwr.get("rssi"),
                "snr": stats.get("snr"),
            },
            "last_seen": n.get("lastSeen"),
            "interview_stage": n.get("interviewStage"),
            "firmware_version": n.get("firmwareVersion"),
            "values": n.get("values", []),
        }

    # ---- commands ----
    async def send_command(self, command: str, **params: Any) -> Any:
        """Send an arbitrary command in a fresh session (after start_listening)."""
        import websockets
        extra = {"extra_headers": {"Authorization": f"Bearer {self.token}"}} if self.token else {}
        async with websockets.connect(self.ws_url, max_size=2**26, **extra) as ws:
            await self.negotiate_schema(ws)
            msg = {"messageId": self._next_id(), "command": command, **params}
            await ws.send(json.dumps(msg))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
                resp = json.loads(raw)
                if resp.get("messageId") != msg["messageId"]:
                    continue
                if resp.get("type") == "error":
                    raise ZwjsError(f"{command} failed: {resp.get('errorCode')}: {resp.get('message')}")
                if resp.get("type") == "result":
                    return resp.get("result")

    async def ping_node(self, node_id: int) -> Any:
        return await self.send_command("node_ping", nodeId=node_id)

    async def refresh_values(self, node_id: int) -> Any:
        return await self.send_command("node_refresh_values", nodeId=node_id)

    async def refresh_info(self, node_id: int) -> Any:
        return await self.send_command("node_refresh_info", nodeId=node_id)

    async def heal_node(self, node_id: int) -> Any:
        return await self.send_command("node_heal_network", nodeId=node_id)

    async def begin_heal(self) -> Any:
        return await self.send_command("begin_healing_network")

    async def set_config_parameter(self, node_id: int, param: int, value: Any,
                                   value_size: int | None = None) -> Any:
        p: dict[str, Any] = {"nodeId": node_id, "parameter": param, "value": value}
        if value_size:
            p["valueSize"] = value_size
        return await self.send_command("node_set_value", **{
            "nodeId": node_id,
            "value": {"commandClass": 112, "property": param, "value": value},
        })
