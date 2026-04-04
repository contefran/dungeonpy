"""
Tests for WSBridge: WebSocket server wrapping GameServer.

Each test receives a live bridge via the `bridge` fixture (no password, no TLS),
which starts on an ephemeral port and tears down automatically after each test.
No mocks — this tests the actual asyncio + websockets plumbing.

All connections must complete a hello handshake before sending intents.
The `dm_hello` / `player_hello` helpers encapsulate that boilerplate.
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
    b = WSBridge(ws_server, host='localhost', port=0)
    b.start()
    yield b
    b.stop()


@pytest.fixture
def bridge_pw(ws_server):
    """Bridge with a DM password set."""
    b = WSBridge(ws_server, host='localhost', port=0, password='secret')
    b.start()
    yield b
    b.stop()


def ws_url(b: WSBridge) -> str:
    return f"ws://{b.host}:{b.port}"


def run(coro):
    return asyncio.run(coro)


async def dm_hello(ws):
    """Send DM hello and return the hello_ack + initial snapshot."""
    await ws.send(json.dumps({"type": "hello", "role": "dm", "name": "DM"}))
    ack = json.loads(await ws.recv())
    snapshot = json.loads(await ws.recv())
    return ack, snapshot


async def player_hello(ws, name="Alice"):
    """Send player hello and return the hello_ack + initial snapshot."""
    await ws.send(json.dumps({"type": "hello", "role": "player", "name": name}))
    ack = json.loads(await ws.recv())
    snapshot = json.loads(await ws.recv())
    return ack, snapshot


# ---------------------------------------------------------------------------
# Handshake
# ---------------------------------------------------------------------------

def test_dm_hello_accepted_no_password(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            ack, snap = await dm_hello(ws)
            return ack, snap
    ack, snap = run(_test())
    assert ack["ok"] is True
    assert ack["role"] == "dm"
    assert snap["type"] == "snapshot"


def test_player_hello_accepted(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            ack, snap = await player_hello(ws, "Thorin")
            return ack, snap
    ack, snap = run(_test())
    assert ack["ok"] is True
    assert ack["role"] == "player"
    assert snap["type"] == "snapshot"


def test_dm_hello_correct_password(bridge_pw):
    async def _test():
        async with websockets.connect(ws_url(bridge_pw)) as ws:
            await ws.send(json.dumps({"type": "hello", "role": "dm",
                                       "name": "DM", "password": "secret"}))
            ack = json.loads(await ws.recv())
            return ack
    ack = run(_test())
    assert ack["ok"] is True


def test_dm_hello_wrong_password_rejected(bridge_pw):
    async def _test():
        async with websockets.connect(ws_url(bridge_pw)) as ws:
            await ws.send(json.dumps({"type": "hello", "role": "dm",
                                       "name": "DM", "password": "wrong"}))
            ack = json.loads(await ws.recv())
            return ack
    ack = run(_test())
    assert ack["ok"] is False
    assert "password" in ack["reason"]


def test_unknown_role_rejected(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await ws.send(json.dumps({"type": "hello", "role": "spectator", "name": "X"}))
            ack = json.loads(await ws.recv())
            return ack
    ack = run(_test())
    assert ack["ok"] is False


def test_snapshot_contains_full_state_fields(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            _, snap = await dm_hello(ws)
            return snap
    state = run(_test())["state"]
    assert "combatants" in state
    assert "active_index" in state
    assert "turn" in state
    assert "player_selection_locks" in state
    assert "player_move_locks" in state
    assert "map_grid" in state


# ---------------------------------------------------------------------------
# WS DM client sends intent → receives event
# ---------------------------------------------------------------------------

def test_ws_intent_advance_turn(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
            await ws.send(json.dumps({"action": "advance_turn"}))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "event"
    assert msg["action"] == "turn_advanced"
    assert "seq" in msg


def test_ws_intent_add_combatant(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
            await ws.send(json.dumps({
                "action": "add_combatant",
                "combatant": {"name": "Gandalf", "initiative": 18},
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["action"] == "combatant_added"
    assert msg["combatant"]["name"] == "Gandalf"


# ---------------------------------------------------------------------------
# Invalid intent → error
# ---------------------------------------------------------------------------

def test_invalid_action_returns_error(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
            await ws.send(json.dumps({"action": "cast_fireball"}))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "cast_fireball" in msg["reason"]


def test_missing_field_returns_error(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
            await ws.send(json.dumps({"action": "apply_damage", "name": "X"}))
            return json.loads(await ws.recv())
    assert run(_test())["type"] == "error"


# ---------------------------------------------------------------------------
# Player permissions
# ---------------------------------------------------------------------------

def test_player_cannot_advance_turn(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await player_hello(ws, "Thorin")
            await ws.send(json.dumps({"action": "advance_turn"}))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "not permitted" in msg["reason"]


def test_player_cannot_move_another_token(bridge, ws_server):
    ws_server.combatants = []
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await player_hello(ws, "Thorin")
            await ws.send(json.dumps({
                "action": "move_token", "name": "Gandalf", "pos": [1, 1]
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "own token" in msg["reason"]


def test_player_move_blocked_when_locked(bridge, ws_server):
    """Player movement is blocked by default (locked)."""
    from Core.combatant import Combatant
    ws_server.combatants = [Combatant("Thorin", 15, pos=[0, 0])]
    ws_server.player_move_locks["Thorin"] = False
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await player_hello(ws, "Thorin")
            await ws.send(json.dumps({
                "action": "move_token", "name": "Thorin", "pos": [1, 1]
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "not currently allowed" in msg["reason"]


def test_player_move_allowed_when_unlocked(bridge, ws_server):
    from Core.combatant import Combatant
    ws_server.combatants = [Combatant("Thorin", 15, pos=[0, 0])]
    ws_server.player_move_locks["Thorin"] = True
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await player_hello(ws, "Thorin")
            await ws.send(json.dumps({
                "action": "move_token", "name": "Thorin", "pos": [2, 3]
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "event"
    assert msg["action"] == "token_moved"


def test_set_player_lock_only_for_dm(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await player_hello(ws, "Thorin")
            await ws.send(json.dumps({
                "action": "set_player_lock", "name": "Thorin",
                "lock_type": "move", "locked": True
            }))
            return json.loads(await ws.recv())
    msg = run(_test())
    assert msg["type"] == "error"
    assert "not permitted" in msg["reason"]


# ---------------------------------------------------------------------------
# player_connected / player_disconnected events
# ---------------------------------------------------------------------------

def test_player_connected_event_broadcast(bridge):
    """DM should receive a player_connected event when a player joins."""
    async def _test():
        async with (
            websockets.connect(ws_url(bridge)) as dm_ws,
            websockets.connect(ws_url(bridge)) as p_ws,
        ):
            await dm_hello(dm_ws)
            await player_hello(p_ws, "Gimli")
            msg = json.loads(await asyncio.wait_for(dm_ws.recv(), timeout=2.0))
            return msg
    msg = run(_test())
    assert msg["action"] == "player_connected"
    assert msg["name"] == "Gimli"


# ---------------------------------------------------------------------------
# Broadcast
# ---------------------------------------------------------------------------

def test_broadcast_reaches_all_clients(bridge):
    async def _test():
        async with (
            websockets.connect(ws_url(bridge)) as ws1,
            websockets.connect(ws_url(bridge)) as ws2,
        ):
            await dm_hello(ws1)
            await dm_hello(ws2)
            await ws1.send(json.dumps({"action": "advance_turn"}))
            m1 = json.loads(await ws1.recv())
            m2 = json.loads(await ws2.recv())
        return m1, m2
    m1, m2 = run(_test())
    assert m1["action"] == "turn_advanced"
    assert m2["action"] == "turn_advanced"


def test_broadcast_seq_identical_across_clients(bridge):
    async def _test():
        async with (
            websockets.connect(ws_url(bridge)) as ws1,
            websockets.connect(ws_url(bridge)) as ws2,
        ):
            await dm_hello(ws1)
            await dm_hello(ws2)
            await ws1.send(json.dumps({"action": "advance_turn"}))
            m1 = json.loads(await ws1.recv())
            m2 = json.loads(await ws2.recv())
        return m1["seq"], m2["seq"]
    s1, s2 = run(_test())
    assert s1 == s2


# ---------------------------------------------------------------------------
# In-process submit (GUI thread path)
# ---------------------------------------------------------------------------

def test_in_process_submit_reaches_ws_client(bridge):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
            bridge.submit({"action": "advance_turn"})
            return json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
    assert run(_test())["action"] == "turn_advanced"


def test_in_process_submit_state_visible_after_ack(bridge, ws_server):
    async def _test():
        async with websockets.connect(ws_url(bridge)) as ws:
            await dm_hello(ws)
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
            await dm_hello(ws)
            await ws.send(json.dumps({
                "action": "advance_turn",
                "client_req_id": "my-req-42",
            }))
            return json.loads(await ws.recv())
    assert run(_test()).get("client_req_id") == "my-req-42"
