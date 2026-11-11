"""Application state: builds observatory node objects by keying on the HA
device registry (grouping entities by device_id, never entity-name matching),
computes scores and problems, maintains caches."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from .actions import ActionManager
from .config import get_config
from .db import Database
from .ha import HAClient
from .influx import InfluxClient
from .problems import detect_controller_problems, detect_node_problems, rank_problems
from .scoring import compute_network_score, compute_node_score
from .zwjs import ZwjsClient

BATTERY_ENTITIES_HINT = ("sensor.battery", "binary_sensor.tampering")


class AppState:
    def __init__(self, db: Database):
        cfg = get_config()
        self.db = db
        self.ha = HAClient(cfg.hass_url, cfg.hass_token or "")
        self.zwjs = ZwjsClient(cfg.zwjs_ws_url, cfg.zwjs_token)
        self.influx = InfluxClient(cfg.influx_url, cfg.influx_org,
                                   cfg.influx_token or "") if cfg.influx_configured() else None
        self.actions = ActionManager(db)
        self.nodes: list[dict[str, Any]] = []
        self.nodes_by_id: dict[int, dict[str, Any]] = {}
        self.prev_stats: dict[int, dict[str, Any]] = {}
        self.status_history: dict[int, list[str]] = {}
        self.chatty_rates: dict[int, float] = {}
        self.jam_share: float = 0.0
        self.network_score: dict[str, Any] | None = None
        self._refresh_lock = asyncio.Lock()
        self._last_refresh: float = 0.0
        self._ws_clients: list[Any] = []

    # ---------- node construction ----------
    async def refresh(self) -> list[dict[str, Any]]:
        async with self._refresh_lock:
            state = await self.zwjs.get_state()
            raw_nodes = state.get("nodes", [])
            device_map = await self._device_entity_map()
            nodes = []
            for n in raw_nodes:
                node = ZwjsClient.shape_node(n)
                did = node.get("device_id")
                entities = device_map.get(str(did), [])
                node["entities"] = [
                    {"entity_id": e.get("entity_id"), "name": e.get("original_name")}
                    for e in entities
                ]
                node["power_source"] = self._infer_power_source(n, entities)
                score = compute_node_score(
                    node,
                    status_history=self.status_history.get(node["node_id"], []),
                    messages_per_hour=self.chatty_rates.get(node["node_id"], 0.0))
                node["health_score"] = score
                prev = self.prev_stats.get(node["node_id"])
                problems = detect_node_problems(
                    node, prev_stats=prev,
                    ha_state_changes_per_hour=self.chatty_rates.get(node["node_id"]),
                    frame_rate_per_hour=self.chatty_rates.get(node["node_id"], 0.0))
                node["problems"] = problems
                self.prev_stats[node["node_id"]] = dict(node["statistics"])
                hist = self.status_history.setdefault(node["node_id"], [])
                if not hist or hist[-1] != node.get("status"):
                    hist.append(node.get("status") or "alive")
                nodes.append(node)
            self.nodes = nodes
            self.nodes_by_id = {n["node_id"]: n for n in nodes}
            self.network_score = compute_network_score(
                {n["node_id"]: n["health_score"] | {"status": n.get("status")} for n in nodes},
                jam_share=self.jam_share)
            self.db.add_score(None, None, None,
                              self.network_score.get("total"), self.network_score.get("grade"))
            for n in nodes:
                self.db.add_score(n["node_id"], n["health_score"]["total"],
                                  n["health_score"]["grade"])
            self._last_refresh = time.time()
            return nodes

    async def _device_entity_map(self) -> dict[str, list[dict[str, Any]]]:
        try:
            return await self.ha.group_entities_by_device()
        except Exception:
            return {}

    @staticmethod
    def _infer_power_source(node: dict[str, Any], entities: list[dict[str, Any]]) -> str:
        for v in node.get("values", []) or []:
            if v.get("commandClass") == 128:  # Battery CC
                return "battery"
        for e in entities:
            if "battery" in (e.get("entity_id") or ""):
                return "battery"
        return "mains"

    def ensure_fresh(self, max_age: float = 60.0) -> None:
        pass  # refresh is driven by endpoints/scheduler

    # ---------- problems / score ----------
    def get_problems(self) -> list[dict[str, Any]]:
        problems: list[dict[str, Any]] = []
        for n in self.nodes:
            problems.extend(n.get("problems", []))
        problems.extend(detect_controller_problems(self.jam_share))
        dismissed = self.db.active_dismissals()

        def key(p: dict[str, Any]) -> str:
            return f"{p['type']}:{p.get('node_id')}:{p['message'][:40]}"

        ranked = [p for p in rank_problems(problems) if key(p) not in dismissed]
        return ranked

    def get_score(self) -> dict[str, Any]:
        per_node = {n["node_id"]: {
            "total": n["health_score"]["total"],
            "grade": n["health_score"]["grade"],
            "status": n.get("status")} for n in self.nodes}
        net = compute_network_score(
            per_node, jam_share=self.jam_share)
        return {"network": net, "nodes": {
            nid: {"total": v["total"], "grade": v["grade"]}
            for nid, v in per_node.items()}}

    # ---------- history ----------
    async def node_history(self, node_id: int, days: int = 7) -> dict[str, Any]:
        out: dict[str, Any] = {"frames": [], "rssi": [], "drops": []}
        if not self.influx:
            return out
        try:
            frames = await self.influx.frames_history(node_id, days)
            rssi = await self.influx.rssi_history(node_id, days)
            drops = await self.influx.drops_history(node_id, days)
            out = {"frames": frames, "rssi": rssi, "drops": drops}
        except Exception as e:
            out["error"] = str(e)
        return out

    async def update_chatty_rates(self) -> None:
        for n in self.nodes:
            entity_ids = [e["entity_id"] for e in n.get("entities", []) if e.get("entity_id")]
            if not entity_ids:
                continue
            try:
                rate = await self.ha.count_state_changes(entity_ids, hours=1.0)
                self.chatty_rates[n["node_id"]] = rate
            except Exception:
                continue

    def broadcast(self, payload: dict[str, Any]) -> None:
        for ws in list(self._ws_clients):
            try:
                asyncio.get_running_loop().create_task(ws.send_json(payload))
            except Exception:
                pass
