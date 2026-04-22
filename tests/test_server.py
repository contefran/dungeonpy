import pytest
from Core.server import GameServer


def make(name, initiative, hp=10):
    return {"name": name, "initiative": initiative, "hp": hp}


@pytest.fixture
def server():
    return GameServer()


def add(server, name, initiative, hp=10):
    server.process_intent(
        {"action": "add_combatant", "combatant": make(name, initiative, hp)}
    )


# --- add / sort ---


def test_add_sorts_by_initiative(server):
    add(server, "B", 5)
    add(server, "A", 15)
    add(server, "C", 10)
    assert [c.name for c in server.combatants] == ["A", "C", "B"]


def test_add_equal_initiative_stable(server):
    add(server, "A", 10)
    add(server, "B", 10)
    assert len(server.combatants) == 2


# --- advance_turn ---


def test_advance_turn_advances_index(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 0
    server.process_intent({"action": "advance_turn"})
    assert server.active_index == 1


def test_advance_turn_wraps_and_increments_turn(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    server.turn = 1
    server.process_intent({"action": "advance_turn"})
    assert server.active_index == 0
    assert server.turn == 2


def test_advance_turn_empty_no_crash(server):
    server.process_intent({"action": "advance_turn"})  # should not raise


def test_condition_timer_expires_on_advance(server):
    # A (init 20) has Invisible expiring round 3 @ init 20.
    # After advancing into round 3 with A active (init 20), condition should be gone.
    add(server, "A", 20)
    server.turn = 1
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {
                "conditions": ["Invisible"],
                "condition_timers": {"Invisible": [3, 20]},
            },
        }
    )
    server.turn = 2
    server.process_intent(
        {"action": "advance_turn"}
    )  # turn becomes 3, active = A (init 20)
    assert "Invisible" not in server.combatants[0].conditions
    assert "Invisible" not in server.combatants[0].condition_timers


def test_condition_timer_not_expired_before_turn(server):
    add(server, "A", 20)
    server.turn = 1
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Blind"], "condition_timers": {"Blind": [5, 20]}},
        }
    )
    server.process_intent({"action": "advance_turn"})  # turn becomes 2
    assert "Blind" in server.combatants[0].conditions


def test_condition_timer_not_expired_same_round_higher_init(server):
    # Two combatants: A (init 20), B (init 10). Blind expires round 2 @ init 10.
    # When we advance into round 2 with A active (init 20 > 10), not yet expired.
    add(server, "A", 20)
    add(server, "B", 10)
    server.turn = 1
    server.active_index = 1  # B is active
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Blind"], "condition_timers": {"Blind": [2, 10]}},
        }
    )
    server.process_intent(
        {"action": "advance_turn"}
    )  # wraps to round 2, A active (init 20)
    assert "Blind" in server.combatants[0].conditions


def test_condition_timer_expires_at_matching_initiative(server):
    # Advance one more step: now B is active (init 10), should expire.
    add(server, "A", 20)
    add(server, "B", 10)
    server.turn = 1
    server.active_index = 1  # B is active
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Blind"], "condition_timers": {"Blind": [2, 10]}},
        }
    )
    server.process_intent(
        {"action": "advance_turn"}
    )  # round 2, A active (init 20) — not expired
    server.process_intent(
        {"action": "advance_turn"}
    )  # round 2, B active (init 10) — expires
    assert "Blind" not in server.combatants[0].conditions


def test_condition_timer_partial_expiry(server):
    add(server, "A", 20)
    server.turn = 1
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {
                "conditions": ["Blind", "Invisible"],
                "condition_timers": {"Blind": [2, 20], "Invisible": [5, 20]},
            },
        }
    )
    server.process_intent(
        {"action": "advance_turn"}
    )  # turn becomes 2, A active (init 20)
    assert "Blind" not in server.combatants[0].conditions
    assert "Invisible" in server.combatants[0].conditions


def test_dead_clears_condition_timers(server):
    add(server, "A", 20)
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Blind"], "condition_timers": {"Blind": [5, 20]}},
        }
    )
    server.process_intent(
        {"action": "update_combatant", "name": "A", "fields": {"conditions": ["Dead"]}}
    )
    assert server.combatants[0].condition_timers == {}


def test_advance_turn_skips_dead(server):
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.process_intent(
        {"action": "update_combatant", "name": "B", "fields": {"conditions": ["Dead"]}}
    )
    server.active_index = 0
    server.process_intent({"action": "advance_turn"})
    assert server.combatants[server.active_index].name == "C"


def test_advance_turn_all_dead_no_crash(server):
    add(server, "A", 20)
    server.process_intent(
        {"action": "update_combatant", "name": "A", "fields": {"conditions": ["Dead"]}}
    )
    server.active_index = 0
    server.process_intent({"action": "advance_turn"})  # should not raise or loop
    assert server.active_index == 0


# --- retreat_turn ---


def test_retreat_turn_retreats_index(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    server.process_intent({"action": "retreat_turn"})
    assert server.active_index == 0


def test_retreat_turn_wraps_and_decrements_turn(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 0
    server.turn = 3
    server.process_intent({"action": "retreat_turn"})
    assert server.active_index == 1
    assert server.turn == 2


def test_retreat_turn_floor_is_one(server):
    add(server, "A", 20)
    server.active_index = 0
    server.turn = 1
    server.process_intent({"action": "retreat_turn"})
    assert server.turn == 1


def test_retreat_turn_empty_no_crash(server):
    server.process_intent({"action": "retreat_turn"})  # should not raise


def test_retreat_turn_skips_dead(server):
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.process_intent(
        {"action": "update_combatant", "name": "B", "fields": {"conditions": ["Dead"]}}
    )
    server.active_index = 2
    server.process_intent({"action": "retreat_turn"})
    assert server.combatants[server.active_index].name == "A"


def test_retreat_turn_all_dead_no_crash(server):
    add(server, "A", 20)
    server.process_intent(
        {"action": "update_combatant", "name": "A", "fields": {"conditions": ["Dead"]}}
    )
    server.active_index = 0
    server.process_intent({"action": "retreat_turn"})  # should not raise or loop
    assert server.active_index == 0


# --- get_active ---


def test_get_active(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    assert server.get_active().name == "B"


def test_get_active_empty(server):
    assert server.get_active() is None


# --- apply_damage ---


def test_apply_damage_reduces_hp(server):
    add(server, "A", 10, hp=20)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 15


def test_apply_damage_floors_at_zero(server):
    add(server, "A", 10, hp=3)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    assert server.combatants[0].hp == 0


def test_apply_damage_adds_down_at_zero(server):
    add(server, "A", 10, hp=3)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    assert "Unconscious" in server.combatants[0].conditions


def test_apply_damage_no_duplicate_down(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {
                "name": "A",
                "initiative": 10,
                "hp": 3,
                "conditions": ["Unconscious"],
            },
        }
    )
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    assert server.combatants[0].conditions.count("Unconscious") == 1


def test_apply_damage_partial_does_not_add_down(server):
    add(server, "A", 10, hp=10)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert "Unconscious" not in server.combatants[0].conditions


def test_apply_damage_none_hp_treated_as_zero(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "A", "initiative": 10, "hp": None},
        }
    )
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 0
    assert "Unconscious" in server.combatants[0].conditions


# --- apply_heal ---


def test_apply_heal_increases_hp(server):
    add(server, "A", 10, hp=5)
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 8})
    assert server.combatants[0].hp == 13


def test_apply_heal_removes_down(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {
                "name": "A",
                "initiative": 10,
                "hp": 0,
                "conditions": ["Unconscious"],
            },
        }
    )
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert "Unconscious" not in server.combatants[0].conditions
    assert server.combatants[0].hp == 5


def test_apply_heal_zero_does_not_remove_down(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {
                "name": "A",
                "initiative": 10,
                "hp": 0,
                "conditions": ["Unconscious"],
            },
        }
    )
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 0})
    assert "Unconscious" in server.combatants[0].conditions


def test_apply_heal_none_hp_treated_as_zero(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "A", "initiative": 10, "hp": None},
        }
    )
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 10})
    assert server.combatants[0].hp == 10


def test_apply_heal_capped_at_max_hp(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "A", "initiative": 10, "hp": 8, "max_hp": 10},
        }
    )
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 10


def test_apply_heal_no_cap_without_max_hp(server):
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "A", "initiative": 10, "hp": 8},
        }
    )
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 13


# --- update_combatant ---


def test_dead_condition_clears_others(server):
    add(server, "A", 10)
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Poisoned", "Stunned"]},
        }
    )
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"conditions": ["Poisoned", "Dead"]},
        }
    )
    assert server.combatants[0].conditions == ["Dead"]


def test_update_combatant_notes(server):
    add(server, "A", 10)
    server.process_intent(
        {
            "action": "update_combatant",
            "name": "A",
            "fields": {"notes": "has the amulet"},
        }
    )
    assert server.combatants[0].notes == "has the amulet"


def test_update_combatant_initiative_triggers_sort(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.process_intent(
        {"action": "update_combatant", "name": "B", "fields": {"initiative": 30}}
    )
    assert server.combatants[0].name == "B"
    assert server.combatants[1].name == "A"


# --- delete_combatant ---


def test_delete_combatant_removes_it(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.process_intent({"action": "delete_combatant", "name": "A"})
    assert len(server.combatants) == 1
    assert server.combatants[0].name == "B"


def test_delete_active_combatant_clamps_index(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    server.process_intent({"action": "delete_combatant", "name": "B"})
    assert server.active_index == 0


def test_delete_combatant_before_active_shifts_index(server):
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.active_index = 2
    server.process_intent({"action": "delete_combatant", "name": "A"})
    assert server.active_index == 1  # shifted down by one
    assert server.combatants[server.active_index].name == "C"


# --- move_up / move_down ---


def test_move_up_same_initiative(server):
    add(server, "A", 10)
    add(server, "B", 10)
    server.process_intent({"action": "move_up", "name": "B"})
    assert server.combatants[0].name == "B"
    assert server.combatants[1].name == "A"


def test_move_down_same_initiative(server):
    add(server, "A", 10)
    add(server, "B", 10)
    server.process_intent({"action": "move_down", "name": "A"})
    assert server.combatants[0].name == "B"
    assert server.combatants[1].name == "A"


def test_move_up_blocked_by_different_initiative(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.process_intent({"action": "move_up", "name": "B"})
    assert server.combatants[0].name == "A"  # unchanged
    assert server.combatants[1].name == "B"


def test_move_down_blocked_by_different_initiative(server):
    add(server, "A", 20)
    add(server, "B", 10)
    server.process_intent({"action": "move_down", "name": "A"})
    assert server.combatants[0].name == "A"  # unchanged


def test_move_up_at_top_no_crash(server):
    add(server, "A", 10)
    server.process_intent({"action": "move_up", "name": "A"})  # no-op


def test_move_active_combatant_updates_index(server):
    add(server, "A", 10)
    add(server, "B", 10)
    server.active_index = 0  # A is active
    server.process_intent({"action": "move_down", "name": "A"})
    assert server.active_index == 1  # followed A to its new position
    assert server.combatants[server.active_index].name == "A"


# --- save / load roundtrip ---


def test_save_load_roundtrip(server, tmp_path):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    server.turn = 3
    server.map_path = "/some/map.txt"

    path = str(tmp_path / "combat.json")
    server.process_intent({"action": "save", "path": path})

    s2 = GameServer()
    s2.process_intent({"action": "load", "path": path})

    assert len(s2.combatants) == 2
    assert s2.combatants[0].name == "A"
    assert s2.combatants[1].name == "B"
    assert s2.active_index == 1
    assert s2.turn == 3
    assert s2.map_path == "/some/map.txt"
    assert s2.map_visible is False  # always hidden on session resume


def test_load_replaces_existing_combatants(server, tmp_path):
    add(server, "A", 20)
    path = str(tmp_path / "combat.json")
    server.process_intent({"action": "save", "path": path})

    s2 = GameServer()
    add(s2, "OldGuy", 99)
    s2.process_intent({"action": "load", "path": path})

    assert all(c.name != "OldGuy" for c in s2.combatants)


# --- pub/sub ---


def test_submit_broadcasts_to_subscribers(server):
    received = []
    server.subscribe(received.append)
    add(server, "A", 10)
    server.submit({"action": "apply_damage", "name": "A", "amount": 3})
    assert any(e.get("action") == "combatant_updated" for e in received)


def test_submit_broadcasts_to_all_subscribers(server):
    log1, log2 = [], []
    server.subscribe(log1.append)
    server.subscribe(log2.append)
    add(server, "A", 10)
    server.submit({"action": "advance_turn"})
    assert len(log1) == len(log2)


# --- load_map ---


def test_load_map_strips_npcs_keeps_pcs(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("010\n111\n010\n")
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "Alice", "initiative": 10, "is_pc": True},
        }
    )
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {"name": "Goblin", "initiative": 8, "is_pc": False},
        }
    )
    server.process_intent({"action": "load_map", "path": str(map_file)})
    names = [c.name for c in server.combatants]
    assert "Alice" in names
    assert "Goblin" not in names


def test_load_map_resets_pc_initiative_and_pos(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("010\n111\n010\n")
    server.process_intent(
        {
            "action": "add_combatant",
            "combatant": {
                "name": "Alice",
                "initiative": 18,
                "is_pc": True,
                "pos": [3, 4],
            },
        }
    )
    server.process_intent({"action": "load_map", "path": str(map_file)})
    alice = server.combatants[0]
    assert alice.initiative == 1
    assert alice.pos is None


def test_load_map_sets_map_visible_true(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("111\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.map_visible is True
    assert server.map_path == str(map_file)


def test_load_map_loads_grid(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("012\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.map_grid == [[0, 1, 2]]


def test_load_map_emits_map_loaded_and_snapshot(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("1\n")
    events = server.process_intent({"action": "load_map", "path": str(map_file)})
    assert events[0]["action"] == "map_loaded"
    assert events[1]["type"] == "snapshot"


def test_load_map_resets_door_states(server, tmp_path):
    map_file = tmp_path / "dungeon.txt"
    map_file.write_text("1\n")
    server.door_states[(0, 1)] = "open"
    server.iron_door_states[(2, 3)] = "open"
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.door_states == {}
    assert server.iron_door_states == {}


def test_load_map_invalid_path_ignored(server):
    events = server.process_intent(
        {"action": "load_map", "path": "/nonexistent/map.txt"}
    )
    assert events == []


# --- set_map_visible ---


def test_set_map_visible_true(server):
    events = server.process_intent({"action": "set_map_visible", "visible": True})
    assert server.map_visible is True
    assert events[0]["action"] == "map_visibility_changed"
    assert events[0]["visible"] is True


def test_set_map_visible_false(server):
    server.map_visible = True
    events = server.process_intent({"action": "set_map_visible", "visible": False})
    assert server.map_visible is False
    assert events[0]["visible"] is False


# --- tile highlights ---


def test_highlight_tile_add(server):
    events = server.process_intent(
        {"action": "highlight_tile", "pos": [3, 2], "owner": "DM", "color": "gold"}
    )
    assert events[0]["action"] == "highlights_changed"
    assert {"pos": [3, 2], "color": "gold", "owner": "DM"} in server.tile_highlights


def test_highlight_tile_toggle_off(server):
    server.process_intent(
        {"action": "highlight_tile", "pos": [3, 2], "owner": "DM", "color": "gold"}
    )
    server.process_intent(
        {"action": "highlight_tile", "pos": [3, 2], "owner": "DM", "color": "gold"}
    )
    assert server.tile_highlights == []


def test_clear_highlights(server):
    server.process_intent(
        {"action": "highlight_tile", "pos": [1, 1], "owner": "DM", "color": "gold"}
    )
    server.process_intent(
        {"action": "highlight_tile", "pos": [2, 2], "owner": "Thorin", "color": "red"}
    )
    server.process_intent({"action": "clear_highlights", "owner": "DM"})
    assert all(h["owner"] != "DM" for h in server.tile_highlights)
    assert any(h["owner"] == "Thorin" for h in server.tile_highlights)


def test_highlight_in_snapshot(server):
    server.process_intent(
        {"action": "highlight_tile", "pos": [5, 3], "owner": "DM", "color": "gold"}
    )
    state = server.get_snapshot()["state"]
    assert "tile_highlights" in state
    assert {"pos": [5, 3], "color": "gold", "owner": "DM"} in state["tile_highlights"]


def test_load_map_clears_highlights(server, tmp_path):
    server.tile_highlights = [{"pos": [1, 1], "color": "gold", "owner": "DM"}]
    map_file = tmp_path / "map.txt"
    map_file.write_text("111\n101\n111\n")
    server.process_intent({"action": "load_map", "path": str(map_file)})
    assert server.tile_highlights == []
