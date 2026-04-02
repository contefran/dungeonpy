"""
Tests for WSBridge: WebSocket server wrapping GameServer.

Each test spins up a real WSBridge on an ephemeral port (port=0), connects one
or more real WebSocket clients, exercises the protocol, and tears down cleanly.
No mocks — this tests the actual asyncio + websockets plumbing.
"""

import asyncio
import json
import pytest
import websockets

from Core.server import GameServer
from Core.ws_bridge import WSBridge


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_bridge(snapshot_interval=0) -> tuple[GameServer, WSBridge]:
    """Create and start a WSBridge on an OS-assigned ephemeral port."""
    server = GameServer(snapshot_interval=snapshot_interval)
    bridge = WSBridge(server, port=0)
    bridge.start()
    return server, bridge


def ws_url(bridge: WSBridge) -> str:
    return f"ws://{bridge.host}:{bridge.port}"


def run(coro):
    """Run an async coroutine from synchronous test code."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Connect → immediate snapshot
# ---------------------------------------------------------------------------

def test_connect_receives_snapshot():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                msg = json.loads(await ws.recv())
            return msg
        msg = run(_test())
        assert msg["type"] == "snapshot"
        assert "state" in msg
    finally:
        bridge.stop()


def test_snapshot_contains_full_state_fields():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                return json.loads(await ws.recv())
        msg = run(_test())
        state = msg["state"]
        assert "combatants" in state
        assert "active_index" in state
        assert "turn" in state
    finally:
        bridge.stop()


# ---------------------------------------------------------------------------
# WS client sends intent → receives event
# ---------------------------------------------------------------------------

def test_ws_intent_advance_turn():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()  # discard snapshot
                await ws.send(json.dumps({"action": "advance_turn"}))
                return json.loads(await ws.recv())
        msg = run(_test())
        assert msg["type"] == "event"
        assert msg["action"] == "turn_advanced"
        assert "seq" in msg
    finally:
        bridge.stop()


def test_ws_intent_add_combatant():
    server, bridge = make_bridge()
    try:
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
    finally:
        bridge.stop()


# ---------------------------------------------------------------------------
# Invalid intent → error event
# ---------------------------------------------------------------------------

def test_invalid_action_returns_error():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()
                await ws.send(json.dumps({"action": "cast_fireball"}))
                return json.loads(await ws.recv())
        msg = run(_test())
        assert msg["type"] == "error"
        assert "cast_fireball" in msg["reason"]
    finally:
        bridge.stop()


def test_missing_field_returns_error():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()
                await ws.send(json.dumps({"action": "apply_damage", "name": "X"}))  # missing amount
                return json.loads(await ws.recv())
        msg = run(_test())
        assert msg["type"] == "error"
    finally:
        bridge.stop()


# ---------------------------------------------------------------------------
# Broadcast: all connected clients receive every event
# ---------------------------------------------------------------------------

def test_broadcast_reaches_all_clients():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with (
                websockets.connect(ws_url(bridge)) as ws1,
                websockets.connect(ws_url(bridge)) as ws2,
            ):
                await ws1.recv()   # snapshots
                await ws2.recv()
                await ws1.send(json.dumps({"action": "advance_turn"}))
                m1 = json.loads(await ws1.recv())
                m2 = json.loads(await ws2.recv())
            return m1, m2
        m1, m2 = run(_test())
        assert m1["action"] == "turn_advanced"
        assert m2["action"] == "turn_advanced"
    finally:
        bridge.stop()


def test_broadcast_seq_identical_across_clients():
    """Both clients must see the same seq number for the same event."""
    server, bridge = make_bridge()
    try:
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
    finally:
        bridge.stop()


# ---------------------------------------------------------------------------
# In-process submit (GUI thread path) reaches WS client
# ---------------------------------------------------------------------------

def test_in_process_submit_reaches_ws_client():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()  # discard snapshot
                bridge.submit({"action": "advance_turn"})
                return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
        msg = run(_test())
        assert msg["action"] == "turn_advanced"
    finally:
        bridge.stop()


def test_in_process_submit_state_visible_immediately():
    """After an in-process submit completes, server state reflects the change."""
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()
                bridge.submit({
                    "action": "add_combatant",
                    "combatant": {"name": "Legolas", "initiative": 20},
                })
                await asyncio.wait_for(ws.recv(), timeout=2.0)  # wait for processing
        run(_test())
        assert any(c.name == "Legolas" for c in server.combatants)
    finally:
        bridge.stop()


# ---------------------------------------------------------------------------
# client_req_id echo
# ---------------------------------------------------------------------------

def test_client_req_id_echoed_on_ws_event():
    server, bridge = make_bridge()
    try:
        async def _test():
            async with websockets.connect(ws_url(bridge)) as ws:
                await ws.recv()
                await ws.send(json.dumps({
                    "action": "advance_turn",
                    "client_req_id": "my-req-42",
                }))
                return json.loads(await ws.recv())
        msg = run(_test())
        assert msg.get("client_req_id") == "my-req-42"
    finally:
        bridge.stop()
