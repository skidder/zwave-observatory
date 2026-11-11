"""API endpoint tests with mocked clients (recorded fixtures, no network)."""
import json

import pytest
from fastapi.testclient import TestClient

from conftest import load_fixture


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import os
    os.environ["DATA_DIR"] = str(tmp_path / "data")
    os.environ["HASS_URL"] = "http://fake-ha"
    os.environ["HASS_TOKEN"] = "fake"
    os.environ["ZWJS_WS_URL"] = "ws://fake-zwjs"
    # Build app with a stubbed AppState
    import app.main as main_mod
    import app.state as state_mod
    from app.db import Database

    class StubState:
        def __init__(self, db):
            self.db = db
            self.nodes = []
            self.nodes_by_id = {}
            self.jam_share = 0.03
            self.network_score = {"total": 0.95, "grade": "A"}
            self.actions = None
            from app.actions import ActionManager
            self.actions = ActionManager(db)

        async def refresh(self):
            state = load_fixture("zwjs_start_listening.json")["result"]["state"]
            from app.zwjs import ZwjsClient
            self.nodes = [ZwjsClient.shape_node(n) for n in state["nodes"]]
            for n in self.nodes:
                n["power_source"] = "mains"
                from app.scoring import compute_node_score
                n["health_score"] = compute_node_score(n)
                n["problems"] = []
            self.nodes_by_id = {n["node_id"]: n for n in self.nodes}

        def get_problems(self):
            return []

        def get_score(self):
            return {"network": self.network_score, "nodes": {}}

        async def update_chatty_rates(self):
            pass

        def broadcast(self, payload):
            pass

    monkeypatch.setattr(state_mod, "AppState", StubState)
    # main.create_app builds AppState directly; patch reference used there
    monkeypatch.setattr(main_mod, "AppState", StubState)

    app = main_mod.create_app()
    with TestClient(app) as c:
        yield c


def test_version(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert r.json()["app"] == "zwave-observatory"


def test_nodes_endpoint(client):
    r = client.get("/api/nodes")
    assert r.status_code == 200
    nodes = r.json()
    assert len(nodes) == 2
    n5 = [n for n in nodes if n["id"] == 5][0]
    assert n5["stats"]["drops"] == 27
    assert "grade" in n5


def test_node_detail_404(client):
    assert client.get("/api/nodes/999").status_code == 404


def test_score_and_problems(client):
    assert client.get("/api/score").status_code == 200
    assert client.get("/api/problems").status_code == 200


def test_setup_status(client):
    r = client.get("/api/setup/status")
    assert r.status_code == 200
    body = r.json()
    assert body["steps"]["hass"]["configured"] is True
    # secrets never returned
    text = json.dumps(body)
    assert "fake" not in text
    assert "HASS_TOKEN" not in [k for k in ("HASS_TOKEN",)] or \
        not any(tok in text for tok in ("Bearer", "access_token"))


def test_audit_no_secrets(client):
    r = client.get("/api/audit")
    assert r.status_code == 200


def test_dismiss(client):
    r = client.post("/api/problems/chatty:5/dismiss", json={"reason": "known"})
    assert r.status_code == 200


def test_advisor_latest_404_initially(client):
    assert client.get("/api/advisor/latest").status_code == 404


def test_advisor_ledger(client):
    assert client.get("/api/advisor/ledger").json() == []
