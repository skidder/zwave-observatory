"""Advisor validator tests: action enum, node existence, param ranges,
duplicate-pending rejection, confirmed-within-14d guard, ledger append-only."""
import json

from app.advisor import ACTIONS_ALLOWED, validate_action
from app.db import Database

NODES = {
    5: {"node_id": 5, "status": "alive", "values": [
        {"commandClass": 112, "property": 3, "value": 3,
         "metadata": {"min": 0, "max": 10, "states": {"0": "off", "3": "3"}}},
        {"commandClass": 112, "property": 11, "value": 0,
         "metadata": {"min": 0, "max": 1}},
    ]},
    1: {"node_id": 1, "status": "alive", "values": []},
}


def rec(action="ping", node_id=5, parameters=None, refs=None, explanation="do it"):
    return {"action": action, "node_id": node_id, "parameters": parameters or {},
            "problem_refs": refs or [], "explanation": explanation}


def test_valid_ping_passes():
    assert validate_action(rec(), NODES, [], []) == []


def test_action_enum_rejected():
    errs = validate_action(rec(action="factory_reset"), NODES, [], [])
    assert any("not in allowed enum" in e for e in errs)


def test_unknown_node_rejected():
    errs = validate_action(rec(node_id=99), NODES, [], [])
    assert any("does not exist" in e for e in errs)


def test_param_range_rejected():
    errs = validate_action(rec(action="set_config_parameter",
                               parameters={"parameter": 3, "value": 55}),
                           NODES, [], [])
    assert any("outside device metadata range" in e for e in errs)


def test_param_state_rejected():
    errs = validate_action(rec(action="set_config_parameter",
                               parameters={"parameter": 3, "value": 7}),
                           NODES, [], [])
    assert any("not in labeled states" in e for e in errs)


def test_unknown_param_rejected():
    errs = validate_action(rec(action="set_config_parameter",
                               parameters={"parameter": 42, "value": 1}),
                           NODES, [], [])
    assert any("not present in device metadata" in e for e in errs)


def test_duplicate_pending_rejected():
    pending = [{"id": 7, "action": "heal_node", "node_id": 5,
                "problem_refs": ["timeout:5"]}]
    errs = validate_action(rec(action="heal_node", node_id=5,
                               refs=["timeout:5"]), NODES, pending, [])
    assert any("duplicates open pending" in e for e in errs)
    # different refs -> allowed
    errs2 = validate_action(rec(action="heal_node", node_id=5,
                                refs=["rssi:5"]), NODES, pending, [])
    assert errs2 == []


def test_confirmed_improvement_guard():
    confirmed = [{"id": 3, "action": "heal_node", "node_id": 5,
                  "problem_refs": ["timeout:5"]}]
    errs = validate_action(rec(action="heal_node", node_id=5, refs=["timeout:5"],
                               explanation=""), NODES, [], confirmed)
    assert any("within 14 days without explanation" in e for e in errs)
    # with explanation -> allowed
    errs2 = validate_action(rec(action="heal_node", node_id=5, refs=["timeout:5"],
                                explanation="regressed after firmware update"),
                            NODES, [], confirmed)
    assert errs2 == []


def test_automation_reference_guard():
    errs = validate_action(rec(refs=["light.bedroom"]), NODES, [], [],
                           automation_refs={"entity_refs": ["light.bedroom"]})
    assert any("automation" in e for e in errs)


def test_ledger_append_only(tmp_db: Database):
    aid = tmp_db.append_ledger_action(1, "heal_node", 5, {"param": 3},
                                      ["timeout:5"], "fix timeouts")
    row = tmp_db.get_ledger()[0]
    assert row["verification_status"] == "pending"
    tmp_db.update_ledger_verification(aid, "confirmed_improvement", "timeout dropped")
    row = tmp_db.get_ledger()[0]
    assert row["verification_status"] == "confirmed_improvement"
    # invalid status rejected; rows can never be deleted/rewritten
    import pytest
    with pytest.raises(ValueError):
        tmp_db.update_ledger_verification(aid, "bogus_status")
    # 7-day window query
    assert len(tmp_db.get_ledger(days=7)) == 1


def test_open_pending_listing(tmp_db: Database):
    tmp_db.append_ledger_action(1, "ping", 5, None, ["chatty:5"], "check")
    tmp_db.append_ledger_action(2, "ping", 1, None, ["chatty:1"], "check")
    tmp_db.update_ledger_verification(2, "no_change")
    open_p = tmp_db.open_pending_actions()
    assert len(open_p) == 1 and open_p[0]["node_id"] == 5
