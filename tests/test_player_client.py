"""
Tests for PlayerClient — client-side state mirroring.

PlayerClient._apply_snapshot() and _apply_incremental() are synchronous
methods that can be tested without a network connection.
"""

import pytest
from Core.server import GameServer
from Core.combatant import Combatant
from Core.player_client import PlayerClient


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client_and_mirror():
    """Return a (PlayerClient, mirror_server) pair. No network is started."""
    mirror = GameServer(snapshot_interval=0)
    client = PlayerClient(server=mirror, host="localhost", port=8765, name="Alice")
    return client, mirror


# ---------------------------------------------------------------------------
# _parse_key_dict
# ---------------------------------------------------------------------------

def test_parse_key_dict_converts_string_keys(client_and_mirror):
    client, _ = client_and_mirror
    result = client._parse_key_dict({"1,2": "open", "3,4": "closed"})
    assert result[(1, 2)] == "open"
    assert result[(3, 4)] == "closed"


def test_parse_key_dict_empty(client_and_mirror):
    client, _ = client_and_mirror
    assert client._parse_key_dict({}) == {}


# ---------------------------------------------------------------------------
# _apply_snapshot
# ---------------------------------------------------------------------------

def _minimal_state(**overrides):
    """Return a minimal valid snapshot state dict."""
    base = {
        "combatants": [],
        "active_index": 0,
        "turn": 1,
        "door_states": {},
        "iron_door_states": {},
        "secret_door_states": {},
        "trap_states": {},
        "player_selection_locks": {},
        "player_move_locks": {},
        "map_path": None,
        "map_visible": False,
        "tile_highlights": [],
        "map_objects": [],
        "light_sources": [],
        "visibility_radius": 10,
        "explored_tiles": [],
        "map_grid": None,
    }
    base.update(overrides)
    return base


def test_snapshot_sets_combatants(client_and_mirror):
    client, mirror = client_and_mirror
    state = _minimal_state(combatants=[{"name": "Goblin", "initiative": 8, "hp": 5}])
    client._apply_snapshot(state)
    assert len(mirror.combatants) == 1
    assert mirror.combatants[0].name == "Goblin"


def test_snapshot_sets_turn(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(turn=5))
    assert mirror.turn == 5


def test_snapshot_sets_active_index(client_and_mirror):
    client, mirror = client_and_mirror
    state = _minimal_state(
        combatants=[
            {"name": "A", "initiative": 20},
            {"name": "B", "initiative": 10},
        ],
        active_index=1,
    )
    client._apply_snapshot(state)
    assert mirror.active_index == 1


def test_snapshot_sets_map_visible(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(map_visible=True))
    assert mirror.map_visible is True


def test_snapshot_sets_visibility_radius(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(visibility_radius=12))
    assert mirror.visibility_radius == 12


def test_snapshot_sets_light_sources(client_and_mirror):
    client, mirror = client_and_mirror
    ls = [{"pos": [1, 1], "radius": 3, "color": "warm", "alpha": 60}]
    client._apply_snapshot(_minimal_state(light_sources=ls))
    assert len(mirror.light_sources) == 1
    assert mirror.light_sources[0]["color"] == "warm"


def test_snapshot_sets_map_objects(client_and_mirror):
    client, mirror = client_and_mirror
    objs = [{"pos": [2, 3], "icon": "chest.png", "width": 1, "height": 1}]
    client._apply_snapshot(_minimal_state(map_objects=objs))
    assert len(mirror.map_objects) == 1


def test_snapshot_sets_explored_tiles_for_own_player(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(explored_tiles=[[1, 1], [2, 2]]))
    assert (1, 1) in mirror.explored_tiles.get("Alice", set())
    assert (2, 2) in mirror.explored_tiles.get("Alice", set())


def test_snapshot_sets_door_states(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(door_states={"1,2": "open"}))
    assert mirror.door_states[(1, 2)] == "open"


def test_snapshot_sets_iron_door_states(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(iron_door_states={"3,4": "closed"}))
    assert mirror.iron_door_states[(3, 4)] == "closed"


def test_snapshot_sets_map_grid(client_and_mirror):
    client, mirror = client_and_mirror
    grid = [[1, 2], [0, 1]]
    client._apply_snapshot(_minimal_state(map_grid=grid))
    assert mirror.map_grid == grid


def test_snapshot_sets_tile_highlights(client_and_mirror):
    client, mirror = client_and_mirror
    hl = [{"pos": [1, 1], "color": "gold", "owner": "DM"}]
    client._apply_snapshot(_minimal_state(tile_highlights=hl))
    assert mirror.tile_highlights == hl


def test_snapshot_sets_player_locks(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_snapshot(_minimal_state(
        player_selection_locks={"Alice": True},
        player_move_locks={"Alice": False},
    ))
    assert mirror.player_selection_locks["Alice"] is True
    assert mirror.player_move_locks["Alice"] is False


# ---------------------------------------------------------------------------
# _apply_incremental — combatant events
# ---------------------------------------------------------------------------

def test_incremental_combatant_updated(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("Goblin", 8, hp=10)]
    client._apply_incremental({
        "action": "combatant_updated",
        "combatant": {"name": "Goblin", "initiative": 8, "hp": 3},
    })
    assert mirror.combatants[0].hp == 3


def test_incremental_combatant_added(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "combatant_added",
        "combatant": {"name": "Orc", "initiative": 12, "hp": 15},
    })
    assert len(mirror.combatants) == 1
    assert mirror.combatants[0].name == "Orc"


def test_incremental_combatant_added_sorted_by_initiative(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("A", 20)]
    client._apply_incremental({
        "action": "combatant_added",
        "combatant": {"name": "B", "initiative": 5},
    })
    assert mirror.combatants[0].name == "A"
    assert mirror.combatants[1].name == "B"


def test_incremental_combatant_removed(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("Orc", 12)]
    client._apply_incremental({"action": "combatant_removed", "name": "Orc"})
    assert len(mirror.combatants) == 0


def test_incremental_token_moved(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("Alice", 15, pos=[0, 0])]
    client._apply_incremental({"action": "token_moved", "name": "Alice", "pos": [3, 4]})
    assert mirror.combatants[0].pos == [3, 4]


def test_incremental_token_placed(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("Alice", 15)]
    client._apply_incremental({"action": "token_placed", "name": "Alice", "pos": [2, 2]})
    assert mirror.combatants[0].pos == [2, 2]


def test_incremental_turn_advanced(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.combatants = [Combatant("A", 20), Combatant("B", 10)]
    client._apply_incremental({"action": "turn_advanced", "turn": 3, "active": "B"})
    assert mirror.turn == 3
    assert mirror.active_index == 1


# ---------------------------------------------------------------------------
# _apply_incremental — door events
# ---------------------------------------------------------------------------

def test_incremental_wooden_door_toggled(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "door_toggled", "x": 3, "y": 2, "tile_type": 3, "state": "open",
    })
    assert mirror.door_states[(2, 3)] == "open"


def test_incremental_iron_door_toggled(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "door_toggled", "x": 1, "y": 1, "tile_type": 4, "state": "open",
    })
    assert mirror.iron_door_states[(1, 1)] == "open"


def test_incremental_secret_door_toggled(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "door_toggled", "x": 2, "y": 0, "tile_type": 5, "state": "closed",
    })
    assert mirror.secret_door_states[(0, 2)] == "closed"


def test_incremental_trap_toggled(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "door_toggled", "x": 4, "y": 3, "tile_type": 6, "state": "open",
    })
    assert mirror.trap_states[(3, 4)] == "open"


# ---------------------------------------------------------------------------
# _apply_incremental — map / light / object events
# ---------------------------------------------------------------------------

def test_incremental_light_source_added(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "light_source_added",
        "light": {"pos": [2, 3], "radius": 5, "color": "warm", "alpha": 60},
    })
    assert len(mirror.light_sources) == 1
    assert mirror.light_sources[0]["color"] == "warm"


def test_incremental_light_source_removed(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.light_sources = [{"pos": [2, 3], "radius": 5, "color": "warm", "alpha": 60}]
    client._apply_incremental({"action": "light_source_removed", "pos": [2, 3]})
    assert len(mirror.light_sources) == 0


def test_incremental_map_object_added(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "map_object_added",
        "object": {"pos": [1, 2], "icon": "chest.png", "width": 1, "height": 1},
    })
    assert len(mirror.map_objects) == 1


def test_incremental_map_object_removed(client_and_mirror):
    client, mirror = client_and_mirror
    mirror.map_objects = [{"pos": [1, 2], "icon": "chest.png", "width": 1, "height": 1}]
    client._apply_incremental({"action": "map_object_removed", "pos": [1, 2]})
    assert len(mirror.map_objects) == 0


# ---------------------------------------------------------------------------
# _apply_incremental — player / visibility events
# ---------------------------------------------------------------------------

def test_incremental_player_lock_changed_move(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "player_lock_changed", "name": "Alice", "lock_type": "move", "locked": True,
    })
    assert mirror.player_move_locks["Alice"] is True


def test_incremental_player_lock_changed_select(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({
        "action": "player_lock_changed", "name": "Alice", "lock_type": "select", "locked": True,
    })
    assert mirror.player_selection_locks["Alice"] is True


def test_incremental_map_visibility_changed(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({"action": "map_visibility_changed", "visible": True})
    assert mirror.map_visible is True


def test_incremental_highlights_changed(client_and_mirror):
    client, mirror = client_and_mirror
    hl = [{"pos": [1, 1], "color": "gold", "owner": "DM"}]
    client._apply_incremental({"action": "highlights_changed", "highlights": hl})
    assert mirror.tile_highlights == hl


def test_incremental_visibility_radius_changed(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({"action": "visibility_radius_changed", "radius": 8})
    assert mirror.visibility_radius == 8


def test_incremental_explored_updated(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({"action": "explored_updated", "new_tiles": [[1, 1], [2, 2]]})
    assert (1, 1) in mirror.explored_tiles.get("Alice", set())
    assert (2, 2) in mirror.explored_tiles.get("Alice", set())


def test_incremental_explored_updated_accumulates(client_and_mirror):
    client, mirror = client_and_mirror
    client._apply_incremental({"action": "explored_updated", "new_tiles": [[1, 1]]})
    client._apply_incremental({"action": "explored_updated", "new_tiles": [[2, 2]]})
    assert (1, 1) in mirror.explored_tiles["Alice"]
    assert (2, 2) in mirror.explored_tiles["Alice"]
