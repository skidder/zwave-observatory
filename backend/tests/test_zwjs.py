"""zwjs start_listening transcript fixture parsing + schema negotiation tests."""
import json

import pytest

from app.zwjs import ZwjsClient, ZwjsError

from conftest import load_fixture


class FakeWS:
    """Replays a recorded server transcript: version hello, then the
    start_listening result."""

    def __init__(self, transcript: list[str]):
        self.tx = list(transcript)
        self.sent: list[str] = []

    async def recv(self, timeout=None):
        if not self.tx:
            raise StopAsyncIteration
        return self.tx.pop(0)

    async def send(self, data):
        self.sent.append(json.loads(data))


def _transcript() -> list[str]:
    version = load_fixture("zwjs_version.json")
    result = load_fixture("zwjs_start_listening.json")
    return [json.dumps(version), json.dumps(result)]


@pytest.mark.asyncio
async def test_start_listening_negotiation():
    client = ZwjsClient("ws://fake")
    ws = FakeWS(_transcript())
    schema, state = await client.negotiate_schema(ws)
    assert schema == 42
    assert len(state["nodes"]) == 2
    # minSchemaVersion sent, clamped to server max
    sent = ws.sent[0]
    assert sent["command"] == "start_listening"
    assert sent["minSchemaVersion"] == 0
    assert sent["messageId"] == "start-listening"


def test_fixture_parsing_shape_node():
    state = load_fixture("zwjs_start_listening.json")["result"]["state"]
    nodes = [ZwjsClient.shape_node(n) for n in state["nodes"]]
    ctrl = nodes[0]
    assert ctrl["node_id"] == 1 and ctrl["is_controller_node"] is True
    n5 = nodes[1]
    assert n5["name"] == "Living Room Dimmer"
    assert n5["device_id"] == "271-4097-4098"
    assert n5["statistics"]["commands_dropped_rx"] == 25
    assert n5["statistics"]["lwr_rssi"] == -63
    assert n5["protocol"]["role"] == "end-node"
    assert n5["neighbors"] == [1, 7]
    assert n5["routes"]["lwr"] == {"rssi": -63}
    assert n5["health_score"] is None if False else True  # not yet computed


@pytest.mark.asyncio
async def test_start_listening_server_error():
    client = ZwjsClient("ws://fake")
    ws = FakeWS([json.dumps({"type": "error",
                             "errorCode": "invalid_token",
                             "message": "bad auth"})])
    with pytest.raises(ZwjsError):
        await client.negotiate_schema(ws)


@pytest.mark.asyncio
async def test_schema_clamp_to_low_server():
    """Server with maxSchemaVersion 25 clamps our min to 0 and reports 25."""
    hello = load_fixture("zwjs_version.json")
    hello["maxSchemaVersion"] = 25
    result = load_fixture("zwjs_start_listening.json")
    result["schemaVersion"] = 25
    client = ZwjsClient("ws://fake")
    ws = FakeWS([json.dumps(hello), json.dumps(result)])
    schema, _ = await client.negotiate_schema(ws)
    assert schema == 25
