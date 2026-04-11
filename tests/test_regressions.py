"""
Regression tests — one test per bug that was encountered and fixed.

Each test is annotated with the commit or description of the original bug
so future developers know exactly what scenario it guards against.
"""

import pytest
from Core.server import GameServer
from Core.combatant import Combatant
from Core.player_client import PlayerClient
from Core.protocol import validate_intent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def server():
    return GameServer(snapshot_interval=0)


def add(server, name, initiative, hp=10, is_pc=False):
    server.process_intent({
        "action": "add_combatant",
        "combatant": {"name": name, "initiative": initiative, "hp": hp, "is_pc": is_pc},
    })


# ===========================================================================
# Combatant / save format
# ===========================================================================

def test_condition_timer_old_int_format_migrated():
    """
    Bug: old save files stored condition timers as {cond: round_int}.
    The new format is {cond: [round, initiative]}.
    _migrate_timers() must silently upgrade old saves so they don't crash
    when advance_turn tries to unpack the [round, initiative] pair.

    Commit: 551f416 "Solved bug with timed conditions"
    """
    c = Combatant.from_dict({
        "name": "A",
        "initiative": 10,
        "conditions": ["Invisible"],
        "condition_timers": {"Invisible": 3},   # old integer format
    })
    # Timer should be migrated to [round, 999] so it doesn't crash on unpack
    assert isinstance(c.condition_timers["Invisible"], list)
    assert c.condition_timers["Invisible"] == [3, 999]


def test_condition_timer_new_list_format_preserved():
    """Counterpart: new format must pass through _migrate_timers unchanged."""
    c = Combatant.from_dict({
        "name": "A",
        "initiative": 10,
        "conditions": ["Blind"],
        "condition_timers": {"Blind": [5, 15]},
    })
    assert c.condition_timers["Blind"] == [5, 15]


def test_combatant_from_dict_missing_size_defaults_to_one():
    """
    Bug: old save files did not contain a 'size' field.
    from_dict() must default it to 1 rather than crash or set 0.

    Commit: 889fa22 "Added bigger tokens"
    """
    c = Combatant.from_dict({"name": "X", "initiative": 5})
    assert c.size == 1


def test_combatant_size_clamped_to_minimum_one():
    """
    Defensive: size=0 (or negative) would produce a zero-tile footprint,
    breaking token rendering. Constructor must clamp to ≥ 1.
    """
    c = Combatant("Dragon", 20, size=0)
    assert c.size == 1
    c2 = Combatant("Dragon", 20, size=-3)
    assert c2.size == 1


def test_combatant_from_dict_missing_is_pc_defaults_false():
    """
    Bug: old save files without 'is_pc' would cause all combatants to be
    treated as PCs and survive map loads. Default must be False.
    """
    c = Combatant.from_dict({"name": "Goblin", "initiative": 8})
    assert c.is_pc is False


def test_combatant_from_dict_missing_condition_timers_defaults_empty():
    """
    Old saves had no 'condition_timers' key. Must default to {} to avoid
    KeyError when advance_turn iterates over timers.
    """
    c = Combatant.from_dict({"name": "A", "initiative": 10, "conditions": ["Blind"]})
    assert c.condition_timers == {}


# ===========================================================================
# Server — condition expiry
# ===========================================================================

def test_advance_turn_does_not_crash_with_old_timer_format(server):
    """
    Bug: if a condition timer was stored as an int (old format), advance_turn
    would crash with "cannot unpack non-sequence int".
    _migrate_timers ensures this never reaches process_intent as a raw int.

    Commit: 551f416 "Solved bug with timed conditions"
    """
    add(server, "A", 20)
    # Manually inject old-format timer (simulates loading an old save)
    server.combatants[0].conditions = ["Blind"]
    server.combatants[0].condition_timers = {"Blind": [2, 20]}  # already migrated
    server.turn = 1
    # Should not raise
    server.process_intent({"action": "advance_turn"})
    server.process_intent({"action": "advance_turn"})  # round 2, A active → expires


def test_dead_clears_condition_timers_preventing_ghost_expiry(server):
    """
    Bug: a combatant marked Dead still had pending condition timers, which
    would fire on advance_turn and emit spurious combatant_updated events.
    Setting Dead must wipe all timers.

    Commit: 0b7c90f "Solved bug with canceled conditions"
    """
    add(server, "A", 20)
    server.process_intent({"action": "update_combatant", "name": "A",
                           "fields": {"conditions": ["Blind"],
                                      "condition_timers": {"Blind": [2, 20]}}}),
    server.process_intent({"action": "update_combatant", "name": "A",
                           "fields": {"conditions": ["Dead"]}})
    assert server.combatants[0].condition_timers == {}
    # Advance past the old expiry — must not emit a combatant_updated for the timer
    server.turn = 1
    received = []
    server.subscribe(received.append)
    server.process_intent({"action": "advance_turn"})  # round 2
    timer_updates = [e for e in received
                     if e.get("action") == "combatant_updated"
                     and "Blind" in str(e)]
    assert timer_updates == []


def test_condition_expiry_uses_initiative_not_just_round(server):
    """
    Bug: early implementation compared only round numbers, so a condition
    expiring at round 2 / initiative 10 would incorrectly expire when
    round 2 started at initiative 20.

    Commit: 551f416 "Solved bug with timed conditions"
    """
    add(server, "A", 20)
    add(server, "B", 10)
    server.turn = 1
    server.active_index = 1  # B is active
    server.process_intent({"action": "update_combatant", "name": "A",
                           "fields": {"conditions": ["Blind"],
                                      "condition_timers": {"Blind": [2, 10]}}})
    # Advance to round 2, A active (init 20 > expiry init 10) → NOT yet expired
    server.process_intent({"action": "advance_turn"})
    assert "Blind" in server.combatants[0].conditions

    # Advance to round 2, B active (init 10 == expiry init 10) → NOW expired
    server.process_intent({"action": "advance_turn"})
    assert "Blind" not in server.combatants[0].conditions


# ===========================================================================
# Server — turn / index management
# ===========================================================================

def test_delete_active_combatant_does_not_leave_out_of_range_index(server):
    """
    Bug: deleting the last combatant while it was active set active_index to
    len(combatants), which is one past the end, causing get_active() to return
    None and IndexError elsewhere.

    Commit: 677b3cb "Fixed bug with swapped indices"
    """
    add(server, "A", 20)
    server.active_index = 0
    server.process_intent({"action": "delete_combatant", "name": "A"})
    assert server.active_index == 0
    assert server.get_active() is None   # graceful, not IndexError


def test_delete_combatant_before_active_shifts_index_correctly(server):
    """
    Bug: deleting a combatant at index i < active_index without adjusting
    active_index caused the active marker to point at the wrong combatant.
    """
    add(server, "A", 30)
    add(server, "B", 20)
    add(server, "C", 10)
    server.active_index = 2   # C is active
    server.process_intent({"action": "delete_combatant", "name": "A"})
    # active_index must shift down by 1
    assert server.active_index == 1
    assert server.combatants[server.active_index].name == "C"


def test_advance_turn_skips_dead_combatants(server):
    """
    Bug: advance_turn incremented the index without checking for Dead,
    causing dead combatants to take turns.
    """
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.process_intent({"action": "update_combatant", "name": "B",
                           "fields": {"conditions": ["Dead"]}})
    server.active_index = 0
    server.process_intent({"action": "advance_turn"})
    assert server.combatants[server.active_index].name == "C"


def test_retreat_turn_skips_dead_combatants(server):
    """Same guard on retreat_turn."""
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.process_intent({"action": "update_combatant", "name": "B",
                           "fields": {"conditions": ["Dead"]}})
    server.active_index = 2   # C is active
    server.process_intent({"action": "retreat_turn"})
    assert server.combatants[server.active_index].name == "A"


# ===========================================================================
# Server — HP
# ===========================================================================

def test_wound_to_zero_adds_unconscious_exactly_once(server):
    """
    Bug: applying damage multiple times at 0 HP appended 'Unconscious'
    repeatedly, polluting the conditions list.
    """
    add(server, "A", 10, hp=5)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    assert server.combatants[0].conditions.count("Unconscious") == 1


def test_heal_above_zero_removes_unconscious(server):
    """
    Bug: healing a downed combatant did not remove the Unconscious condition,
    leaving them permanently flagged as down even with positive HP.
    """
    server.process_intent({"action": "add_combatant",
                           "combatant": {"name": "A", "initiative": 10,
                                         "hp": 0, "conditions": ["Unconscious"]}})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert "Unconscious" not in server.combatants[0].conditions
    assert server.combatants[0].hp == 5


def test_heal_to_exactly_zero_keeps_unconscious(server):
    """
    Edge case: healing for 0 (or heal that doesn't raise hp above 0) must
    NOT remove Unconscious.
    """
    server.process_intent({"action": "add_combatant",
                           "combatant": {"name": "A", "initiative": 10,
                                         "hp": 0, "conditions": ["Unconscious"]}})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 0})
    assert "Unconscious" in server.combatants[0].conditions


# ===========================================================================
# Server — map load
# ===========================================================================

def test_load_map_always_hides_map_on_session_resume(server, tmp_path):
    """
    Bug: after a session save, map_visible could be True.  On the next
    launch the map would be shown to players immediately before the DM had
    placed tokens, revealing the empty grid.  load_from_file() must always
    reset map_visible to False.
    """
    server.map_visible = True
    path = str(tmp_path / "save.json")
    server.save_to_file(path)

    s2 = GameServer(snapshot_interval=0)
    s2.load_from_file(path)
    assert s2.map_visible is False


def test_load_map_resets_all_door_states(server, tmp_path):
    """
    Bug: door states from a previous map persisted into the new map,
    causing doors to start open or in the wrong state on load.
    """
    server.door_states[(1, 2)] = "open"
    server.iron_door_states[(3, 4)] = "open"
    server.secret_door_states[(5, 6)] = "open"
    map_file = tmp_path / "map.txt"
    map_file.write_text("111\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.door_states == {}
    assert server.iron_door_states == {}
    assert server.secret_door_states == {}


def test_load_map_keeps_pcs_removes_npcs(server, tmp_path):
    """
    Bug: load_map removed all combatants including PCs, forcing the DM to
    re-enter player characters on every map change.

    Commit: 3ebc32c "solved a bug that caused the map to be forgotten by combatant"
    """
    server.process_intent({"action": "add_combatant",
                           "combatant": {"name": "Alice", "initiative": 15, "is_pc": True}})
    server.process_intent({"action": "add_combatant",
                           "combatant": {"name": "Goblin", "initiative": 8, "is_pc": False}})
    map_file = tmp_path / "map.txt"
    map_file.write_text("1\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    names = [c.name for c in server.combatants]
    assert "Alice" in names
    assert "Goblin" not in names


def test_load_map_resets_pc_position(server, tmp_path):
    """
    Bug: PCs retained their old pos after a load_map, causing them to appear
    on the wrong tile (or off-map) in the new dungeon.
    """
    server.process_intent({"action": "add_combatant",
                           "combatant": {"name": "Alice", "initiative": 15,
                                         "is_pc": True, "pos": [10, 10]}})
    map_file = tmp_path / "map.txt"
    map_file.write_text("1\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    alice = server.combatants[0]
    assert alice.pos is None
    assert alice.initiative == 1   # reset to 1 for re-rolling


# ===========================================================================
# WebSocket — multiplayer
# ===========================================================================

def test_same_player_name_cannot_connect_twice():
    """
    Bug: two clients could connect with the same name, causing map events
    to be applied twice and the DM to see duplicate player rows.

    Commit: bed9e99 "Fixed multiple connections to combatant"
    """
    import asyncio, json, websockets
    from Core.ws_bridge import WSBridge

    bridge = WSBridge(GameServer(), host="localhost", port=0)
    bridge.start()

    async def _test():
        url = f"ws://localhost:{bridge.port}"
        async with websockets.connect(url) as ws1:
            await ws1.send(json.dumps({"type": "hello", "role": "player", "name": "Alice"}))
            ack1 = json.loads(await ws1.recv())
            await ws1.recv()  # snapshot

            async with websockets.connect(url) as ws2:
                await ws2.send(json.dumps({"type": "hello", "role": "player", "name": "Alice"}))
                ack2 = json.loads(await ws2.recv())
                return ack1, ack2

    ack1, ack2 = asyncio.run(_test())
    bridge.stop()

    assert ack1["ok"] is True
    assert ack2["ok"] is False
    assert "already connected" in ack2["reason"]


# ===========================================================================
# PlayerClient — state mirroring
# ===========================================================================

def test_player_client_explored_tiles_accumulate_not_replace():
    """
    Bug: each explored_updated event replaced the explored_tiles set instead
    of unioning into it, causing earlier tiles to disappear from the fog.
    """
    mirror = GameServer(snapshot_interval=0)
    client = PlayerClient(server=mirror, host="localhost", port=8765, name="Alice")

    client._apply_incremental({"action": "explored_updated", "new_tiles": [[1, 1], [2, 2]]})
    client._apply_incremental({"action": "explored_updated", "new_tiles": [[3, 3]]})

    tiles = mirror.explored_tiles.get("Alice", set())
    assert (1, 1) in tiles
    assert (2, 2) in tiles
    assert (3, 3) in tiles   # must not have replaced the first batch


def test_player_client_snapshot_sets_explored_tiles_for_own_name():
    """
    Bug: snapshot applied explored_tiles keyed to a hardcoded name instead of
    self.name, so a player named "Bob" would never see their explored tiles.
    """
    mirror = GameServer(snapshot_interval=0)
    client = PlayerClient(server=mirror, host="localhost", port=8765, name="Bob")

    client._apply_snapshot({
        "combatants": [], "active_index": 0, "turn": 1,
        "door_states": {}, "iron_door_states": {}, "secret_door_states": {},
        "trap_states": {}, "player_selection_locks": {}, "player_move_locks": {},
        "map_path": None, "map_visible": False, "tile_highlights": [],
        "map_objects": [], "light_sources": [], "visibility_radius": 10,
        "explored_tiles": [[5, 5], [6, 6]],
        "map_grid": None,
    })
    assert (5, 5) in mirror.explored_tiles.get("Bob", set())


# ===========================================================================
# Protocol
# ===========================================================================

def test_validate_intent_rejects_missing_action():
    """
    Defensive: a dict without 'action' must be rejected cleanly, not cause
    a KeyError inside the server.
    """
    ok, reason = validate_intent({"name": "something"})
    assert not ok
    assert "action" in reason


def test_validate_intent_rejects_non_dict():
    """
    Defensive: passing a string or None must not raise an exception.
    """
    ok, _ = validate_intent("advance_turn")
    assert not ok
    ok2, _ = validate_intent(None)
    assert not ok2


def test_chat_empty_or_whitespace_text_rejected(server):
    """
    Bug: sending an empty or whitespace-only chat message produced an event
    that the UI displayed as a blank line, cluttering the chat log.
    """
    assert server.process_intent({"action": "chat_message", "text": ""}) == []
    assert server.process_intent({"action": "chat_message", "text": "   "}) == []
    assert server.process_intent({"action": "chat_message", "text": "\t\n"}) == []
