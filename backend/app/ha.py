"""Home Assistant client: REST API + websockets (for device registry and
multi-entity history). States cached 15s, system_log cached 60s."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx


class HAClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._states_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._system_log_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._ws_id = 0
        self._device_registry: list[dict[str, Any]] | None = None
        self._entity_registry: list[dict[str, Any]] | None = None

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    # ---------- REST ----------
    async def get_states(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if not force and self._states_cache and now - self._states_cache[0] < 15:
            return self._states_cache[1]
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base_url}/api/states", headers=self._headers())
            r.raise_for_status()
            states = r.json()
        self._states_cache = (now, states)
        return states

    async def get_state(self, entity_id: str) -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base_url}/api/states/{entity_id}", headers=self._headers())
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()

    async def call_service(self, domain: str, service: str, data: dict[str, Any]) -> Any:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base_url}/api/services/{domain}/{service}",
                             headers=self._headers(), json=data)
            r.raise_for_status()
            return r.json()

    async def get_system_log(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.time()
        if not force and self._system_log_cache and now - self._system_log_cache[0] < 60:
            return self._system_log_cache[1]
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{self.base_url}/api/error_log", headers=self._headers())
            r.raise_for_status()
            entries = [{"raw": r.text}] if isinstance(r.text, str) else r.json()
        self._system_log_cache = (now, entries)
        return entries

    # ---------- WebSocket ----------
    async def _ws_call(self, payload: dict[str, Any], timeout: float = 30.0) -> Any:
        """Send one command over HA WS and wait for its result."""
        try:
            import websockets
        except ImportError:  # pragma: no cover
            websockets = None  # type: ignore
            raise RuntimeError("websockets package required for HA WS")
        ws_url = self.base_url.replace("http", "ws", 1).rstrip("/") + "/api/websocket"
        async with websockets.connect(ws_url, max_size=2**25) as ws:
            hello = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if hello.get("type") != "auth_required":
                raise RuntimeError(f"unexpected HA WS hello: {hello.get('type')}")
            await ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth_ok = json.loads(await asyncio.wait_for(ws.recv(), timeout))
            if auth_ok.get("type") != "auth_ok":
                raise RuntimeError("HA WS auth failed")
            self._ws_id += 1
            msg_id = self._ws_id
            await ws.send(json.dumps({**payload, "id": msg_id}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), timeout))
                if msg.get("id") != msg_id:
                    continue
                if msg.get("type") == "result":
                    if not msg.get("success", False):
                        raise RuntimeError(f"HA WS command failed: {msg.get('error')}")
                    return msg.get("result")
                if msg.get("type") == "auth_invalid":
                    raise RuntimeError("HA WS auth invalid")

    async def get_device_registry(self) -> list[dict[str, Any]]:
        if self._device_registry is None:
            self._device_registry = await self._ws_call({"type": "config/device_registry/list"})
        return self._device_registry

    async def get_entity_registry(self) -> list[dict[str, Any]]:
        if self._entity_registry is None:
            self._entity_registry = await self._ws_call({"type": "config/entity_registry/list"})
        return self._entity_registry

    async def get_history_during_period(self, entity_ids: list[str],
                                        start_ts: str, end_ts: str,
                                        minimal_response: bool = True) -> dict[str, Any]:
        """Multi-entity history via WS history/history_during_period."""
        payload = {
            "type": "history/history_during_period",
            "start_time": start_ts,
            "end_time": end_ts,
            "entity_ids": entity_ids,
            "include_start_time_state": True,
        }
        if minimal_response:
            payload["minimal_response"] = True
        return await self._ws_call(payload, timeout=60.0)

    async def group_entities_by_device(self) -> dict[str, list[dict[str, Any]]]:
        """device_id -> list of entities (from registry). Never name-matching."""
        devices, entities = await asyncio.gather(
            self.get_device_registry(), self.get_entity_registry())
        grouped: dict[str, list[dict[str, Any]]] = {}
        for e in entities:
            did = e.get("device_id")
            if did:
                grouped.setdefault(did, []).append(e)
        for d in devices:
            grouped.setdefault(d["id"], [])
        return grouped

    async def count_state_changes(self, entity_ids: list[str], hours: float) -> float:
        """Lower-bound message rate: number of state changes / hour via history."""
        from datetime import datetime, timedelta, timezone
        end = datetime.now(timezone.utc)
        start = end - timedelta(hours=hours)
        hist = await self.get_history_during_period(
            entity_ids, start.isoformat(), end.isoformat(), minimal_response=True)
        changes = 0
        for eid, states in hist.items():
            if not isinstance(states, list):
                continue
            for a, b in zip(states, states[1:]):
                if a.get("state") != b.get("state"):
                    changes += 1
        return changes / hours if hours > 0 else 0.0
