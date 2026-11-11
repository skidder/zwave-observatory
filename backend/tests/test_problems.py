"""Problem rubric threshold tests."""
import time

from app.problems import (detect_controller_problems, detect_node_problems,
                          rank_problems)


def _node(status="alive", power="mains", rx=100, dropped=0, timeouts=0,
          prev_timeouts=0, rssi=-50, last_seen=None, node_id=5):
    return {
        "node_id": node_id, "status": status, "power_source": power,
        "last_seen": last_seen if last_seen is not None else time.time(),
        "statistics": {"commands_rx": rx, "commands_dropped_rx": dropped,
                       "timeout_response": timeouts, "rssi": rssi},
    }, {"timeout_response": prev_timeouts}


def test_dropped_rx_thresholds():
    node, prev = _node(rx=100, dropped=15)
    probs = detect_node_problems(node, prev_stats=prev)
    kinds = {p["type"]: p["severity"] for p in probs}
    assert kinds["dropped_rx"] == "high"  # 15% > 10%
    node, prev = _node(rx=100, dropped=7)
    kinds = {p["type"]: p["severity"] for p in detect_node_problems(node, prev_stats=prev)}
    assert kinds["dropped_rx"] == "medium"  # 7% in 5-10%
    node, prev = _node(rx=100, dropped=3)
    assert not any(p["type"] == "dropped_rx" for p in detect_node_problems(node, prev_stats=prev))


def test_timeout_new_vs_rising():
    node, prev = _node(timeouts=3, prev_timeouts=0)
    probs = detect_node_problems(node, prev_stats=prev)
    t = [p for p in probs if p["type"] == "timeout"]
    assert t[0]["severity"] == "high"
    node, prev = _node(timeouts=6, prev_timeouts=4)
    t = [p for p in detect_node_problems(node, prev_stats=prev) if p["type"] == "timeout"]
    assert t[0]["severity"] == "medium"


def test_rssi_bands():
    for rssi, sev in ((-90, "high"), (-80, "medium"), (-70, "watch"), (-60, None)):
        node, prev = _node(rssi=rssi)
        probs = [p for p in detect_node_problems(node, prev_stats=prev) if p["type"] == "rssi"]
        if sev is None:
            assert not probs
        else:
            assert probs[0]["severity"] == sev


def test_dead_and_unavailable_high():
    node, _ = _node(status="dead")
    assert detect_node_problems(node)[0]["severity"] == "high"
    node, _ = _node(status="unavailable")
    assert any(p["severity"] == "high" and p["type"] == "unavailable"
               for p in detect_node_problems(node))


def test_staleness_bands():
    for hours, power, sev in ((49, "battery", "high"), (25, "battery", "medium"),
                              (13, "battery", "low"), (3, "mains", "high")):
        node, _ = _node(power=power, last_seen=time.time() - hours * 3600)
        p = [p for p in detect_node_problems(node) if p["type"] == "stale"]
        assert p and p[0]["severity"] == sev, (hours, power)


def test_chatty_bands():
    for rate, sev in ((250, "high"), (150, "medium"), (50, "watch"), (20, None)):
        node, _ = _node()
        probs = [p for p in detect_node_problems(node, ha_state_changes_per_hour=rate)
                 if p["type"] == "chatty"]
        if sev is None:
            assert not probs
        else:
            assert probs[0]["severity"] == sev


def test_chatty_crosscheck_takes_max():
    node, _ = _node()
    probs = [p for p in detect_node_problems(node, ha_state_changes_per_hour=210,
                                             frame_rate_per_hour=40)
             if p["type"] == "chatty"]
    assert probs[0]["severity"] == "high"  # max(210, 40)


def test_jam_thresholds():
    assert detect_controller_problems(0.20)[0]["severity"] == "high"
    assert detect_controller_problems(0.10)[0]["severity"] == "medium"
    assert detect_controller_problems(0.02) == []


def test_ranking_severity_first():
    node, _ = _node(status="dead", rx=100, dropped=50)
    probs = rank_problems(detect_node_problems(node))
    assert probs[0]["severity"] == "high"
    assert probs[0]["type"] in ("dead", "dropped_rx")
