"""Actions: allowed enum, mutating concurrency, heal guard, audit content."""
import asyncio

import pytest

from app.db import Database


class FakeZwjs:
    async def ping_node(self, node_id):
        return {"responded": True}

    async def refresh_values(self, node_id):
        return "ok"

    async def refresh_info(self, node_id):
        return "ok"

    async def heal_node(self, node_id):
        return "healing"

    async def send_command(self, command, **params):
        return [1, 2]

    async def set_config_parameter(self, node_id, param, value, size=None):
        return "set"

    async def get_state(self):
        return {"nodes": [{"nodeId": 5, "values": [
            {"commandClass": 112, "property": 3, "value": 7}]}]}


@pytest.fixture()
def mgr(tmp_db, monkeypatch):
    from app.actions import ActionManager
    m = ActionManager(tmp_db)
    monkeypatch.setattr(m, "_client", lambda: FakeZwjs())
    return m


@pytest.mark.asyncio
async def test_ping_allowed_and_audited(mgr, tmp_db):
    r = await mgr.run_action("ping", 5)
    assert r["result"] == {"responded": True}
    audit = tmp_db.get_audit()
    assert any(a["action"] == "ping" and a["node_id"] == 5 for a in audit)


@pytest.mark.asyncio
async def test_disallowed_action(mgr):
    with pytest.raises(ValueError):
        await mgr.run_action("factory_reset", 5)


@pytest.mark.asyncio
async def test_network_wide_heal_rejected(mgr):
    with pytest.raises(ValueError):
        await mgr.run_action("heal_node", 5, {"network_wide": True})


@pytest.mark.asyncio
async def test_one_mutating_in_flight(mgr, monkeypatch):
    from app.actions import ActionManager
    gate = asyncio.Event()

    class Slow(FakeZwjs):
        async def refresh_values(self, node_id):
            await gate.wait()
            return "ok"

    monkeypatch.setattr(mgr, "_client", lambda: Slow())
    t1 = asyncio.create_task(mgr.run_action("refresh_values", 5))
    await asyncio.sleep(0.05)
    with pytest.raises(RuntimeError):
        await mgr.run_action("re_interview", 5)
    gate.set()
    await t1


@pytest.mark.asyncio
async def test_param_write_verifies_readback(mgr, tmp_db):
    r = await mgr.run_action("set_config_parameter", 5, {"parameter": 3, "value": 7})
    assert r["result"]["verified"] is True
    audit = tmp_db.get_audit()
    params_entries = [a for a in audit if a["action"] == "set_config_parameter"
                      and a.get("params_after")]
    assert params_entries, "audit must include params_after for param writes"
    assert params_entries[0]["params_after"]["parameter"] == 3


@pytest.mark.asyncio
async def test_action_error_audited(mgr, monkeypatch):
    class Boom(FakeZwjs):
        async def ping_node(self, node_id):
            raise RuntimeError("nope")

    monkeypatch.setattr(mgr, "_client", lambda: Boom())
    with pytest.raises(RuntimeError):
        await mgr.run_action("ping", 5)
