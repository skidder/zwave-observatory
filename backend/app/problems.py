"""Problem detection and ranking per severity rubric.

Rubric:
- dropped_rx > 10% -> high; 5-10% -> medium
- timeout: any new -> high; rising -> medium
- rssi < -85 -> high; -75..-85 -> medium; -65..-75 -> low (watch)
- dead / unavailable -> high
- flapping -> medium
- staleness: battery >48h / mains >2h -> high; battery >24h -> medium; battery >12h -> low
- chatty: >200/h high; 100-200 medium; 30-100 low (watch)
- controller jam > 15% -> high; 5-15% -> medium
Chatty detection uses HA state-change counts as a lower bound, cross-checked
against zwave-js frame-counter (commands_tx+commands_rx) deltas.
"""
from __future__ import annotations

import time
from typing import Any

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "watch": 3}


def _ts(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _mk(severity: str, kind: str, node_id: int | None, message: str, **extra: Any) -> dict[str, Any]:
    p = {"severity": severity, "type": kind, "node_id": node_id, "message": message}
    p.update(extra)
    return p


def detect_node_problems(node: dict[str, Any], *, now: float | None = None,
                         prev_stats: dict[str, Any] | None = None,
                         ha_state_changes_per_hour: float | None = None,
                         frame_rate_per_hour: float = 0.0) -> list[dict[str, Any]]:
    now = now if now is not None else time.time()
    stats = node.get("statistics") or {}
    prev = prev_stats or {}
    power = (node.get("power_source") or "mains").lower()
    status = (node.get("status") or "alive").lower()
    problems: list[dict[str, Any]] = []
    asleep = power == "battery" and status == "asleep"

    # dropped_rx
    rx = stats.get("commands_rx") or 0
    dropped = stats.get("commands_dropped_rx") or 0
    if rx > 0 and not asleep:
        frac = dropped / rx
        if frac > 0.10:
            problems.append(_mk("high", "dropped_rx", node["node_id"],
                                f"{frac:.0%} of received commands dropped ({dropped}/{rx})"))
        elif frac >= 0.05:
            problems.append(_mk("medium", "dropped_rx", node["node_id"],
                                f"{frac:.0%} of received commands dropped ({dropped}/{rx})"))

    # timeout: any new -> high, rising -> medium
    timeouts = stats.get("timeout_response") or 0
    prev_timeouts = prev.get("timeout_response") or 0
    if timeouts > prev_timeouts and not asleep:
        delta = timeouts - prev_timeouts
        if prev_timeouts == 0 and delta > 0:
            problems.append(_mk("high", "timeout", node["node_id"],
                                f"{delta} new response timeout(s)"))
        else:
            problems.append(_mk("medium", "timeout", node["node_id"],
                                f"timeout count rising: {prev_timeouts} -> {timeouts}"))

    # rssi
    rssi = stats.get("rssi")
    lwr = stats.get("lwr_rssi")
    cands = [v for v in (rssi, lwr) if isinstance(v, (int, float))]
    best = max(cands) if cands else None
    if best is not None and not asleep:
        if best < -85:
            problems.append(_mk("high", "rssi", node["node_id"], f"rssi {best} dBm < -85"))
        elif best < -75:
            problems.append(_mk("medium", "rssi", node["node_id"], f"rssi {best} dBm in -75..-85"))
        elif best < -65:
            problems.append(_mk("watch", "rssi", node["node_id"], f"rssi {best} dBm in -65..-75"))

    # status
    if status == "dead":
        problems.append(_mk("high", "dead", node["node_id"], "node is dead"))
    elif status == "unavailable":
        problems.append(_mk("high", "unavailable", node["node_id"], "node is unavailable"))

    # staleness (battery asleep nodes are exempt only while asleep)
    last_seen = node.get("last_seen")
    if last_seen and not asleep:
        age_h = (now - _ts(last_seen)) / 3600.0
        if power == "battery":
            if age_h > 48:
                problems.append(_mk("high", "stale", node["node_id"], f"battery node last seen {age_h:.0f}h ago"))
            elif age_h > 24:
                problems.append(_mk("medium", "stale", node["node_id"], f"battery node last seen {age_h:.0f}h ago"))
            elif age_h > 12:
                problems.append(_mk("low", "stale", node["node_id"], f"battery node last seen {age_h:.0f}h ago"))
        else:
            if age_h > 2:
                problems.append(_mk("high", "stale", node["node_id"], f"mains node last seen {age_h:.1f}h ago"))

    # chatty: max(HA state-change lower bound, zwjs frame-counter delta rate)
    chatty_rate = frame_rate_per_hour
    if ha_state_changes_per_hour is not None:
        chatty_rate = max(chatty_rate, ha_state_changes_per_hour)
    if chatty_rate > 200:
        problems.append(_mk("high", "chatty", node["node_id"],
                            f"{chatty_rate:.0f} msgs/h > 200"))
    elif chatty_rate > 100:
        problems.append(_mk("medium", "chatty", node["node_id"],
                            f"{chatty_rate:.0f} msgs/h in 100-200"))
    elif chatty_rate > 30:
        problems.append(_mk("watch", "chatty", node["node_id"],
                            f"{chatty_rate:.0f} msgs/h in 30-100"))

    return problems


def detect_controller_problems(jam_share: float) -> list[dict[str, Any]]:
    if jam_share > 0.15:
        return [_mk("high", "controller_jam", None,
                    f"controller jam share {jam_share:.0%} > 15%")]
    if jam_share >= 0.05:
        return [_mk("medium", "controller_jam", None,
                    f"controller jam share {jam_share:.0%} in 5-15%")]
    return []


def rank_problems(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank: severity first, then by node_id, then by type for stability."""
    def key(p: dict[str, Any]):
        return (SEVERITY_ORDER.get(p["severity"], 9),
                p.get("node_id") if p.get("node_id") is not None else 10**9,
                p.get("type", ""))
    return sorted(problems, key=key)
