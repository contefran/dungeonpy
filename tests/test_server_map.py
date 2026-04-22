"""
Tests for GameServer map-related features:
  - Token placement and movement
  - Fog of war / explored tiles
  - Door toggling (wooden, iron, secret, trap)
  - Map objects (add, remove, snapshot, load_map reset)
  - Light sources (add, remove, clamping, snapshot, load_map reset)
  - Chat messages
  - Visibility radius
  - Recenter broadcast
  - Player management (connected, disconnected, locks)
  - Per-player snapshot filtering
  - Save/load preservation of new fields
"""

import pytest
from Core.server import GameServer


@pytest.fixture
def server():
    return GameServer(snapshot_interval=0)


def add(server, name, initiative, hp=10, is_pc=False):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {
                "name": name,
                "initiative": initiative,
                "hp": hp,
                "is_pc": is_pc,
            },
        }
    )


# ---------------------------------------------------------------------------
# Token placement
# ---------------------------------------------------------------------------


def test_place_token_sets_pos(server):
    add(server, "A", 10)
    server.process_intent({"action": "place_token", "name": "A", "pos": [3, 4]})
    assert server.combatants[0].pos == [3, 4]


def test_place_token_emits_event(server):
    add(server, "A", 10)
    events = server.process_intent(
        {"action": "place_token", "name": "A", "pos": [3, 4]}
    )
    assert events[0]["action"] == "token_placed"
    assert events[0]["name"] == "A"
    assert events[0]["pos"] == [3, 4]


def test_place_token_unknown_name_no_event(server):
    events = server.process_intent(
        {"action": "place_token", "name": "Ghost", "pos": [1, 1]}
    )
    assert events == []


def test_move_token_updates_pos(server):
    add(server, "A", 10)
    server.process_intent({"action": "place_token", "name": "A", "pos": [1, 1]})
    server.process_intent({"action": "move_token", "name": "A", "pos": [5, 5]})
    assert server.combatants[0].pos == [5, 5]


def test_move_token_emits_event(server):
    add(server, "A", 10)
    server.process_intent({"action": "place_token", "name": "A", "pos": [1, 1]})
    events = server.process_intent({"action": "move_token", "name": "A", "pos": [5, 5]})
    assert events[0]["action"] == "token_moved"
    assert events[0]["pos"] == [5, 5]


# ---------------------------------------------------------------------------
# Fog of war — explored tiles
# ---------------------------------------------------------------------------


def test_place_token_updates_explored_tiles(server, tmp_path):
    map_file = tmp_path / "map.txt"
    map_file.write_text("1111\n1111\n1111\n1111\n")
    add(server, "Alice", 10, is_pc=True)
    server.process_intent({"action": "load_map", "path": str(map_file)})
    server.process_intent({"action": "place_token", "name": "Alice", "pos": [1, 1]})
    assert len(server.explored_tiles.get("Alice", set())) > 0


def test_move_token_extends_explored_tiles(server, tmp_path):
    map_file = tmp_path / "map.txt"
    map_file.write_text("1111\n1111\n1111\n1111\n")
    add(server, "Alice", 10, is_pc=True)
    server.process_intent({"action": "load_map", "path": str(map_file)})
    server.process_intent({"action": "place_token", "name": "Alice", "pos": [0, 0]})
    before = len(server.explored_tiles.get("Alice", set()))
    server.process_intent({"action": "move_token", "name": "Alice", "pos": [3, 3]})
    after = len(server.explored_tiles.get("Alice", set()))
    assert after >= before


def test_snapshot_explored_tiles_filtered_per_player(server):
    server.explored_tiles = {
        "Alice": {(1, 1), (2, 2)},
        "Bob": {(3, 3), (4, 4)},
    }
    alice_state = server.get_snapshot(player_name="Alice")["state"]
    bob_state = server.get_snapshot(player_name="Bob")["state"]
    dm_state = server.get_snapshot()["state"]

    alice_tiles = {tuple(t) for t in alice_state["explored_tiles"]}
    bob_tiles = {tuple(t) for t in bob_state["explored_tiles"]}

    assert (1, 1) in alice_tiles
    assert (3, 3) not in alice_tiles
    assert (3, 3) in bob_tiles
    assert (1, 1) not in bob_tiles
    assert dm_state["explored_tiles"] == {}


def test_load_map_resets_explored_tiles(server, tmp_path):
    server.explored_tiles = {"Alice": {(1, 1)}}
    map_file = tmp_path / "map.txt"
    map_file.write_text("1\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.explored_tiles == {}


# ---------------------------------------------------------------------------
# Door toggling
# ---------------------------------------------------------------------------


def test_toggle_wooden_door_opens(server):
    server.process_intent({"action": "toggle_door", "x": 2, "y": 1})
    assert server.door_states[(1, 2)] == "open"


def test_toggle_wooden_door_closes(server):
    server.door_states[(1, 2)] = "open"
    server.process_intent({"action": "toggle_door", "x": 2, "y": 1})
    assert server.door_states[(1, 2)] == "closed"


def test_toggle_door_emits_event(server):
    events = server.process_intent({"action": "toggle_door", "x": 2, "y": 1})
    assert events[0]["action"] == "door_toggled"
    assert events[0]["x"] == 2
    assert events[0]["y"] == 1


def test_toggle_iron_door(server):
    server.process_intent({"action": "toggle_door", "x": 3, "y": 2, "tile_type": 4})
    assert server.iron_door_states.get((2, 3)) == "open"


def test_toggle_secret_door(server):
    server.process_intent({"action": "toggle_door", "x": 1, "y": 0, "tile_type": 5})
    assert server.secret_door_states.get((0, 1)) == "open"


def test_toggle_trap(server):
    server.process_intent({"action": "toggle_door", "x": 4, "y": 4, "tile_type": 6})
    assert server.trap_states.get((4, 4)) == "open"


def test_toggle_door_event_includes_tile_type(server):
    events = server.process_intent(
        {"action": "toggle_door", "x": 1, "y": 1, "tile_type": 4}
    )
    assert events[0]["tile_type"] == 4


# ---------------------------------------------------------------------------
# Map objects
# ---------------------------------------------------------------------------


def test_add_map_object_stores_it(server):
    server.process_intent(
        {
            "action": "add_map_object",
            "pos": [2, 3],
            "icon": "chest.png",
            "width": 1,
            "height": 1,
        }
    )
    assert len(server.map_objects) == 1
    assert server.map_objects[0] == {
        "pos": [2, 3],
        "icon": "chest.png",
        "width": 1,
        "height": 1,
    }


def test_add_map_object_emits_event(server):
    events = server.process_intent(
        {
            "action": "add_map_object",
            "pos": [2, 3],
            "icon": "chest.png",
            "width": 1,
            "height": 1,
        }
    )
    assert events[0]["action"] == "map_object_added"
    assert events[0]["object"]["icon"] == "chest.png"


def test_add_map_object_width_height(server):
    server.process_intent(
        {
            "action": "add_map_object",
            "pos": [1, 1],
            "icon": "table.png",
            "width": 2,
            "height": 1,
        }
    )
    assert server.map_objects[0]["width"] == 2
    assert server.map_objects[0]["height"] == 1


def test_add_map_object_minimum_size_one(server):
    server.process_intent(
        {
            "action": "add_map_object",
            "pos": [0, 0],
            "icon": "rock.png",
            "width": 0,
            "height": -1,
        }
    )
    assert server.map_objects[0]["width"] == 1
    assert server.map_objects[0]["height"] == 1


def test_remove_map_object(server):
    server.process_intent(
        {
            "action": "add_map_object",
            "pos": [2, 3],
            "icon": "chest.png",
            "width": 1,
            "height": 1,
        }
    )
    events = server.process_intent({"action": "remove_map_object", "pos": [2, 3]})
    assert len(server.map_objects) == 0
    assert events[0]["action"] == "map_object_removed"
    assert events[0]["pos"] == [2, 3]


def test_remove_nonexistent_object_returns_no_event(server):
    events = server.process_intent({"action": "remove_map_object", "pos": [9, 9]})
    assert events == []


def test_map_objects_in_snapshot(server):
    server.process_intent(
        {
            "action": "add_map_object",
            "pos": [1, 2],
            "icon": "barrel.png",
            "width": 1,
            "height": 1,
        }
    )
    state = server.get_snapshot()["state"]
    assert len(state["map_objects"]) == 1
    assert state["map_objects"][0]["icon"] == "barrel.png"


def test_load_map_clears_objects(server, tmp_path):
    server.map_objects = [{"pos": [1, 1], "icon": "x.png", "width": 1, "height": 1}]
    map_file = tmp_path / "map.txt"
    map_file.write_text("1\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.map_objects == []


# ---------------------------------------------------------------------------
# Light sources
# ---------------------------------------------------------------------------


def test_add_light_source_stores_it(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [3, 4],
            "radius": 5,
            "color": "warm",
        }
    )
    assert len(server.light_sources) == 1
    ls = server.light_sources[0]
    assert ls["pos"] == [3, 4]
    assert ls["radius"] == 5
    assert ls["color"] == "warm"


def test_add_light_source_emits_event(server):
    events = server.process_intent(
        {
            "action": "add_light_source",
            "pos": [3, 4],
            "radius": 5,
            "color": "warm",
        }
    )
    assert events[0]["action"] == "light_source_added"
    assert events[0]["light"]["color"] == "warm"


def test_add_light_source_alpha_clamped_high(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [0, 0],
            "radius": 3,
            "color": "white",
            "alpha": 300,
        }
    )
    assert server.light_sources[0]["alpha"] == 255


def test_add_light_source_alpha_clamped_low(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [0, 0],
            "radius": 3,
            "color": "white",
            "alpha": -10,
        }
    )
    assert server.light_sources[0]["alpha"] == 0


def test_add_light_source_radius_minimum_one(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [0, 0],
            "radius": 0,
            "color": "warm",
        }
    )
    assert server.light_sources[0]["radius"] == 1


def test_remove_light_source(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [3, 4],
            "radius": 5,
            "color": "warm",
        }
    )
    events = server.process_intent({"action": "remove_light_source", "pos": [3, 4]})
    assert len(server.light_sources) == 0
    assert events[0]["action"] == "light_source_removed"
    assert events[0]["pos"] == [3, 4]


def test_remove_nonexistent_light_returns_no_event(server):
    events = server.process_intent({"action": "remove_light_source", "pos": [9, 9]})
    assert events == []


def test_light_sources_in_snapshot(server):
    server.process_intent(
        {
            "action": "add_light_source",
            "pos": [1, 2],
            "radius": 3,
            "color": "cool",
        }
    )
    state = server.get_snapshot()["state"]
    assert len(state["light_sources"]) == 1


def test_load_map_clears_light_sources(server, tmp_path):
    server.light_sources = [{"pos": [1, 1], "radius": 3, "color": "warm", "alpha": 60}]
    map_file = tmp_path / "map.txt"
    map_file.write_text("1\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.light_sources == []


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


def test_chat_message_emits_event(server):
    events = server.process_intent(
        {
            "action": "chat_message",
            "text": "hello",
            "from": "Alice",
            "to": "DM",
        }
    )
    assert len(events) == 1
    e = events[0]
    assert e["action"] == "chat_message"
    assert e["from"] == "Alice"
    assert e["text"] == "hello"


def test_chat_empty_text_produces_no_event(server):
    assert server.process_intent({"action": "chat_message", "text": "   "}) == []
    assert server.process_intent({"action": "chat_message", "text": ""}) == []


def test_chat_dm_to_player_has_to_field(server):
    events = server.process_intent(
        {
            "action": "chat_message",
            "text": "Watch out!",
            "to": "Alice",
        }
    )
    assert events[0]["to"] == "Alice"


def test_chat_from_defaults_to_dm(server):
    events = server.process_intent({"action": "chat_message", "text": "hi"})
    assert events[0]["from"] == "DM"


# ---------------------------------------------------------------------------
# Visibility radius
# ---------------------------------------------------------------------------


def test_set_visibility_radius(server):
    events = server.process_intent({"action": "set_visibility_radius", "radius": 15})
    assert server.visibility_radius == 15
    assert events[0]["action"] == "visibility_radius_changed"
    assert events[0]["radius"] == 15


def test_visibility_radius_clamped_max(server):
    server.process_intent({"action": "set_visibility_radius", "radius": 100})
    assert server.visibility_radius == 30


def test_visibility_radius_clamped_min(server):
    server.process_intent({"action": "set_visibility_radius", "radius": 0})
    assert server.visibility_radius == 1


def test_visibility_radius_in_snapshot(server):
    server.visibility_radius = 8
    state = server.get_snapshot()["state"]
    assert state["visibility_radius"] == 8


# ---------------------------------------------------------------------------
# Recenter
# ---------------------------------------------------------------------------


def test_recenter_all_emits_event(server):
    events = server.process_intent({"action": "recenter_all", "pos": [5, 6]})
    assert events[0]["action"] == "recenter_all"
    assert events[0]["pos"] == [5, 6]


# ---------------------------------------------------------------------------
# Player management
# ---------------------------------------------------------------------------


def test_player_connected_initializes_locks(server):
    events = server.process_intent(
        {
            "action": "player_connected",
            "name": "Alice",
            "color": "blue",
        }
    )
    assert "Alice" in server.player_selection_locks
    assert "Alice" in server.player_move_locks
    assert events[0]["action"] == "player_connected"
    assert events[0]["name"] == "Alice"
    assert events[0]["color"] == "blue"


def test_player_connected_does_not_override_existing_lock(server):
    server.player_move_locks["Alice"] = True
    server.process_intent(
        {"action": "player_connected", "name": "Alice", "color": "red"}
    )
    assert server.player_move_locks["Alice"] is True


def test_player_disconnected_removes_locks(server):
    server.player_selection_locks["Alice"] = True
    server.player_move_locks["Alice"] = True
    events = server.process_intent({"action": "player_disconnected", "name": "Alice"})
    assert "Alice" not in server.player_selection_locks
    assert "Alice" not in server.player_move_locks
    assert events[0]["action"] == "player_disconnected"


def test_set_player_lock_move(server):
    events = server.process_intent(
        {
            "action": "set_player_lock",
            "name": "Alice",
            "lock_type": "move",
            "locked": True,
        }
    )
    assert server.player_move_locks["Alice"] is True
    assert events[0]["action"] == "player_lock_changed"
    assert events[0]["lock_type"] == "move"


def test_set_player_lock_select(server):
    server.process_intent(
        {
            "action": "set_player_lock",
            "name": "Alice",
            "lock_type": "select",
            "locked": True,
        }
    )
    assert server.player_selection_locks["Alice"] is True


def test_set_player_lock_select_false_clears_highlights(server):
    server.tile_highlights = [{"pos": [1, 1], "color": "blue", "owner": "Alice"}]
    server.player_selection_locks["Alice"] = True
    server.process_intent(
        {
            "action": "set_player_lock",
            "name": "Alice",
            "lock_type": "select",
            "locked": False,
        }
    )
    assert server.player_selection_locks["Alice"] is False
    assert all(h["owner"] != "Alice" for h in server.tile_highlights)


def test_set_player_lock_select_false_clears_selection_event(server):
    server.player_selection_locks["Alice"] = True
    events = server.process_intent(
        {
            "action": "set_player_lock",
            "name": "Alice",
            "lock_type": "select",
            "locked": False,
        }
    )
    actions = [e["action"] for e in events]
    assert "selection_cleared" in actions


# ---------------------------------------------------------------------------
# Save / load — preservation of new fields
# ---------------------------------------------------------------------------


def test_save_load_preserves_light_sources(server, tmp_path):
    server.light_sources = [{"pos": [2, 3], "radius": 4, "color": "warm", "alpha": 80}]
    path = str(tmp_path / "save.json")
    server.save_to_file(path)
    s2 = GameServer(snapshot_interval=0)
    s2.load_from_file(path)
    assert s2.light_sources == [
        {"pos": [2, 3], "radius": 4, "color": "warm", "alpha": 80}
    ]


def test_save_load_preserves_map_objects(server, tmp_path):
    server.map_objects = [{"pos": [1, 2], "icon": "chest.png", "width": 2, "height": 1}]
    path = str(tmp_path / "save.json")
    server.save_to_file(path)
    s2 = GameServer(snapshot_interval=0)
    s2.load_from_file(path)
    assert s2.map_objects == [
        {"pos": [1, 2], "icon": "chest.png", "width": 2, "height": 1}
    ]


def test_save_load_preserves_explored_tiles(server, tmp_path):
    server.explored_tiles = {"Alice": {(1, 1), (2, 2)}}
    path = str(tmp_path / "save.json")
    server.save_to_file(path)
    s2 = GameServer(snapshot_interval=0)
    s2.load_from_file(path)
    assert (1, 1) in s2.explored_tiles.get("Alice", set())
    assert (2, 2) in s2.explored_tiles.get("Alice", set())


def test_save_load_preserves_visibility_radius(server, tmp_path):
    server.visibility_radius = 14
    path = str(tmp_path / "save.json")
    server.save_to_file(path)
    s2 = GameServer(snapshot_interval=0)
    s2.load_from_file(path)
    assert s2.visibility_radius == 14
