"""Scoring math tests, including asleep-battery-no-penalty and jam cap."""
import time

from app.scoring import compute_network_score, compute_node_score, grade_for


def _node(status="alive", power="mains", rx=100, dropped=0, timeouts=0,
          rssi=-50, last_seen=None, **kw):
    return {
        "node_id": 5, "status": status, "power_source": power,
        "last_seen": last_seen if last_seen is not None else time.time(),
        "statistics": {"commands_rx": rx, "commands_dropped_rx": dropped,
                       "timeout_response": timeouts, "rssi": rssi},
        **kw,
    }


def test_perfect_node_scores_a():
    s = compute_node_score(_node())
    assert s["total"] >= 0.9
    assert s["grade"] == "A"


def test_heavy_drops_and_timeouts_score():
    # dropped 30% -> 0.30, 7 timeouts -> 0.20, rssi -88 -> 0.25
    s = compute_node_score(_node(rx=100, dropped=30, timeouts=7, rssi=-88))
    assert s["total"] == 0.25  # 1 - 0.75
    assert {p["penalty"] for p in s["penalties"]} == {0.30, 0.20, 0.25}
    assert s["grade"] == "F"


def test_moderate_drops_b():
    s = compute_node_score(_node(rx=100, dropped=12))  # >10% -> 0.15
    assert s["total"] == 0.85
    assert s["grade"] == "B"


def test_status_dead_penalty():
    s = compute_node_score(_node(status="dead"))
    assert s["total"] == 0.60 and s["grade"] == "C"


def test_stale_battery_48h():
    s = compute_node_score(_node(power="battery", last_seen=time.time() - 49 * 3600))
    assert s["total"] == 0.85
    s2 = compute_node_score(_node(power="battery", last_seen=time.time() - 25 * 3600))
    assert s2["total"] == 0.92


def test_stale_mains_2h():
    s = compute_node_score(_node(power="mains", last_seen=time.time() - 3 * 3600))
    assert s["total"] == 0.85


def test_battery_asleep_no_penalty():
    node = _node(status="asleep", power="battery", rx=10, dropped=10,
                 timeouts=99, rssi=-99, last_seen=time.time() - 100 * 3600)
    s = compute_node_score(node)
    assert s["penalties"] == []
    assert s["total"] == 1.0


def test_flapping_detected():
    s = compute_node_score(_node(),
                           status_history=["alive", "dead", "alive", "dead"])
    assert any(p["reason"] == "status flapping" for p in s["penalties"])
    assert s["total"] == 0.9


def test_chatty_penalties():
    s = compute_node_score(_node(), messages_per_hour=250)
    assert s["total"] == 0.85
    s2 = compute_node_score(_node(), messages_per_hour=150)
    assert s2["total"] == 0.92


def test_grades_boundaries():
    assert grade_for(0.9) == "A"
    assert grade_for(0.75) == "B"
    assert grade_for(0.6) == "C"
    assert grade_for(0.4) == "D"
    assert grade_for(0.39) == "F"


def test_network_score_weighted_mean():
    scores = {
        1: {"total": 1.0, "status": "alive"},
        5: {"total": 0.5, "status": "alive"},
    }
    out = compute_network_score(scores)
    assert out["total"] == 0.75


def test_jam_share_cap():
    scores = {i: {"total": 1.0, "status": "alive"} for i in range(10)}
    out = compute_network_score(scores, jam_share=0.20)
    assert out["total"] == 0.69
    assert "capped" in out["note"]
    # just under cap: no cap
    out2 = compute_network_score(scores, jam_share=0.14)
    assert out2["total"] == 1.0


def test_collision_growth_subtraction():
    scores = {1: {"total": 1.0, "status": "alive"}}
    out = compute_network_score(scores, collision_growth=2, missing_ack_growth=1)
    assert out["total"] == 0.85
