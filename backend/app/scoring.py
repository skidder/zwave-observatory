"""Per-node health scoring: penalty model.

Weights (fraction of score lost):
- dropped_rx (fraction of received commands dropped): 0.30 if >20%, 0.15 if >10%, 0.05 if >2%
- timeout_response: 0.20 if >5, 0.10 if >0 (per window)
- rssi (best of rssi/lwr_rssi, dBm): 0.25 if < -85, 0.12 if < -75, 0.05 if < -65
- status: dead 0.40, unavailable 0.25, flapping 0.10
- stale last_seen: battery >48h -> 0.15, mains >2h -> 0.15, battery >24h 0.08, mains >1h 0.08
- chatty: >200 msgs/h -> 0.15, >100/h -> 0.08

Battery asleep nodes get no penalty (they sleep by design).
Grades: A >= 0.9, B >= 0.75, C >= 0.6, D >= 0.4, else F.
"""
from __future__ import annotations

import time
from typing import Any


def _flapping(status_history: list[str]) -> bool:
    """>=3 status flips among alive/dead/unavailable within the window."""
    flips = 0
    for a, b in zip(status_history, status_history[1:]):
        if a != b:
            flips += 1
    return flips >= 3


def compute_node_score(node: dict[str, Any], *, now: float | None = None,
                       status_history: list[str] | None = None,
                       messages_per_hour: float = 0.0) -> dict[str, Any]:
    now = now if now is not None else time.time()
    stats = node.get("statistics") or {}
    status = (node.get("status") or "alive").lower()
    power = (node.get("power_source") or "mains").lower()
    last_seen = node.get("last_seen")

    penalties: list[dict[str, Any]] = []
    asleep = power == "battery" and status in ("asleep",)

    def add(penalty: float, reason: str) -> None:
        if penalty > 0:
            penalties.append({"penalty": penalty, "reason": reason})

    if not asleep:
        # dropped_rx ratio
        rx = stats.get("commands_rx") or 0
        dropped = stats.get("commands_dropped_rx") or 0
        if rx > 0:
            frac = dropped / rx
            if frac > 0.20:
                add(0.30, f"dropped_rx {frac:.0%} > 20%")
            elif frac > 0.10:
                add(0.15, f"dropped_rx {frac:.0%} > 10%")
            elif frac > 0.02:
                add(0.05, f"dropped_rx {frac:.0%} > 2%")

        # timeouts
        timeouts = stats.get("timeout_response") or 0
        if timeouts > 5:
            add(0.20, f"{timeouts} response timeouts")
        elif timeouts > 0:
            add(0.10, f"{timeouts} response timeouts")

        # rssi
        rssi = stats.get("rssi")
        lwr_rssi = stats.get("lwr_rssi")
        candidates = [v for v in (rssi, lwr_rssi) if isinstance(v, (int, float))]
        best = max(candidates) if candidates else None
        if best is not None:
            if best < -85:
                add(0.25, f"rssi {best} dBm < -85")
            elif best < -75:
                add(0.12, f"rssi {best} dBm < -75")
            elif best < -65:
                add(0.05, f"rssi {best} dBm < -65")

        # status
        if status == "dead":
            add(0.40, "node status dead")
        elif status == "unavailable":
            add(0.25, "node status unavailable")
        elif status_history and _flapping(status_history):
            add(0.10, "status flapping")

        # staleness
        if last_seen:
            age_h = (now - _to_ts(last_seen)) / 3600.0
            stale_thresholds = (
                (48, 0.15), (24, 0.08)
            ) if power == "battery" else (
                (2, 0.15), (1, 0.08)
            )
            for hours, penalty in stale_thresholds:
                if age_h > hours:
                    add(penalty, f"last_seen stale {age_h:.1f}h ({power})")
                    break

        # chatty
        if messages_per_hour > 200:
            add(0.15, f"chatty: {messages_per_hour:.0f} msgs/h > 200")
        elif messages_per_hour > 100:
            add(0.08, f"chatty: {messages_per_hour:.0f} msgs/h > 100")

    total = max(0.0, 1.0 - sum(p["penalty"] for p in penalties))
    return {"total": round(total, 3), "grade": grade_for(total), "penalties": penalties}


def grade_for(total: float) -> str:
    if total >= 0.9:
        return "A"
    if total >= 0.75:
        return "B"
    if total >= 0.6:
        return "C"
    if total >= 0.4:
        return "D"
    return "F"


def _to_ts(last_seen: Any) -> float:
    if isinstance(last_seen, (int, float)):
        return float(last_seen) if last_seen > 1e12 else float(last_seen)
    # ISO 8601 string
    from datetime import datetime, timezone
    s = str(last_seen).replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def compute_network_score(node_scores: dict[int, dict[str, Any]], *,
                          jam_share: float = 0.0,
                          collision_growth: int = 0,
                          missing_ack_growth: int = 0) -> dict[str, Any]:
    """Weighted mean of node scores; jam share > 15% caps at 0.69;
    5-point (0.05) subtraction per unit of collision / missing-ack growth."""
    if not node_scores:
        return {"total": None, "grade": None, "note": "no nodes"}
    weights: dict[str, float] = {"dead": 1.5, "unavailable": 1.25, "alive": 1.0, "asleep": 0.5}
    total_w = 0.0
    acc = 0.0
    for nid, sc in node_scores.items():
        w = weights.get(str(sc.get("status", "alive")).lower(), 1.0)
        acc += sc["total"] * w
        total_w += w
    score = acc / total_w if total_w else 0.0

    capped = False
    if jam_share > 0.15:
        score = min(score, 0.69)
        capped = True
    deductions = 0.05 * (max(0, collision_growth) + max(0, missing_ack_growth))
    if deductions:
        score = max(0.0, score - deductions)
    score = round(max(0.0, score), 3)
    out: dict[str, Any] = {"total": score, "grade": grade_for(score)}
    if capped:
        out["note"] = "capped by controller jam share > 15%"
    if deductions:
        out["note"] = (out.get("note", "") + f" -{deductions:.2f} for collision/missing-ack growth").strip()
    return out
