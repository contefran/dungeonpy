"""
Tests for WSBridge: WebSocket server wrapping GameServer.

Each test receives a live bridge via the `bridge` fixture, which starts on an
ephemeral port and is torn down automatically after each test.
No mocks — this tests the actual asyncio + websockets plumbing.
"""

import asyncio
import json
import pytest
import websockets

from Core.server import GameServer
from Core.ws_bridge import WSBridge


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def ws_server():
    return GameServer()


@pytest.fixture
def bridge(ws_server):
    b = WSBridge(ws_server, port=0)
    b.start()
    yield b
    b.stop()


def ws_url(b: WSBridge) -> str:
    return f"ws://{b.host}:{b.port}"


def run(coro):
    """Run an async coroutine from synchronous test code."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Connect → immediate snapshot
# ---------------------------------------------------------------------------

def test_connect_receives_snapshot(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "snapshot"
    assert "state" in msg


def test_snapshot_contains_full_state_fields(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            return json.loads(await ws.recv())
    state = run(_test())["state"]
    assert "combatants" in state
    assert "active_index" in state
    assert "turn" in state


# ---------------------------------------------------------------------------
# WS client sends intent → receives event
# ---------------------------------------------------------------------------

def test_ws_intent_advance_turn(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()  # discard snapshot
            await ws.send(json.dumps({"action": "advance_turn"}))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "event"
    assert msg["action"] == "turn_advanced"
    assert "seq" in msg


def test_ws_intent_add_combatant(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            await ws.send(json.dumps({
                "action": "add_combatant",
                "combatant": {"name": "Gandalf", "initiative": 18},
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["action"] == "combatant_added"
    assert msg["combatant"]["name"] == "Gandalf"


# ---------------------------------------------------------------------------
# Invalid intent → error event
# ---------------------------------------------------------------------------

def test_invalid_action_returns_error(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            await ws.send(json.dumps({"action": "cast_fireball"}))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "cast_fireball" in msg["reason"]


def test_missing_field_returns_error(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            await ws.send(json.dumps({"action": "apply_damage", "name": "X"}))  # missing amount
            return json.loads(await ws.recv())
    assert run(_test())["type"] == "error"


# ---------------------------------------------------------------------------
# Broadcast: all connected clients receive every event
# ---------------------------------------------------------------------------

def test_broadcast_reaches_all_clients(bridge):
    async def _test():
        async with (
            websockets.connect(ws_url(bridge)) as ws1,
            websockets.connect(ws_url(bridge)) as ws2,
        ):
            await ws1.recv()
            await ws2.recv()
            await ws1.send(json.dumps({"action": "advance_turn"}))
            m1 = json.loads(await ws1.recv())
            m2 = json.loads(await ws2.recv())
        return m1, m2
    m1, m2 = run(_test())
    assert m1["action"] == "turn_advanced"
    assert m2["action"] == "turn_advanced"


def test_broadcast_seq_identical_across_clients(bridge):
    """Both clients must see the same seq number for the same event."""
    async def _test():
        async with (
            websockets.connect(ws_url(bridge)) as ws1,
            websockets.connect(ws_url(bridge)) as ws2,
        ):
            await ws1.recv()
            await ws2.recv()
            await ws1.send(json.dumps({"action": "advance_turn"}))
            m1 = json.loads(await ws1.recv())
            m2 = json.loads(await ws2.recv())
        return m1["seq"], m2["seq"]
    s1, s2 = run(_test())
    assert s1 == s2


# ---------------------------------------------------------------------------
# In-process submit (GUI thread path) reaches WS client
# ---------------------------------------------------------------------------

def test_in_process_submit_reaches_ws_client(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            bridge.submit({"action": "advance_turn"})
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
    assert run(_test())["action"] == "turn_advanced"


def test_in_process_submit_state_visible_after_ack(bridge, ws_server):
    """Server state is updated once the bridge confirms processing (event received)."""
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            bridge.submit({
                "action": "add_combatant",
                "combatant": {"name": "Legolas", "initiative": 20},
            })
            await asyncio.wait_for(ws.recv(), timeout=2.0)
    run(_test())
    assert any(c.name == "Legolas" for c in ws_server.combatants)


# ---------------------------------------------------------------------------
# client_req_id echo
# ---------------------------------------------------------------------------

def test_client_req_id_echoed_on_ws_event(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.recv()
            await ws.send(json.dumps({
                "action": "advance_turn",
                "client_req_id": "my-req-42",
            }))
            return json.loads(await ws.recv())
    assert run(_test()).get("client_req_id") == "my-req-42"
