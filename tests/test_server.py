import pytest
from Core.server import GameServer
from Core.combatant import Combatant


def make(name, initiative, hp=10):
    return {"name": name, "initiative": initiative, "hp": hp}


@pytest.fixture
def server():
    return GameServer()


def add(server, name, initiative, hp=10):
    server.process_intent({"action": "add_combatant", "combatant": make(name, initiative, hp)})


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

def test_advance_turn_skips_dead(server):
    add(server, "A", 20)
    add(server, "B", 10)
    add(server, "C", 5)
    server.process_intent({"action": "update_combatant", "name": "B", "fields": {"conditions": ["Dead"]}})
    server.active_index = 0
    server.process_intent({"action": "advance_turn"})
    assert server.combatants[server.active_index].name == "C"

def test_advance_turn_all_dead_no_crash(server):
    add(server, "A", 20)
    server.process_intent({"action": "update_combatant", "name": "A", "fields": {"conditions": ["Dead"]}})
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
    server.process_intent({"action": "update_combatant", "name": "B", "fields": {"conditions": ["Dead"]}})
    server.active_index = 2
    server.process_intent({"action": "retreat_turn"})
    assert server.combatants[server.active_index].name == "A"

def test_retreat_turn_all_dead_no_crash(server):
    add(server, "A", 20)
    server.process_intent({"action": "update_combatant", "name": "A", "fields": {"conditions": ["Dead"]}})
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
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": 3, "conditions": ["Unconscious"]
    }})
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 10})
    assert server.combatants[0].conditions.count("Unconscious") == 1

def test_apply_damage_partial_does_not_add_down(server):
    add(server, "A", 10, hp=10)
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert "Unconscious" not in server.combatants[0].conditions

def test_apply_damage_none_hp_treated_as_zero(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": None
    }})
    server.process_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 0
    assert "Unconscious" in server.combatants[0].conditions


# --- apply_heal ---

def test_apply_heal_increases_hp(server):
    add(server, "A", 10, hp=5)
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 8})
    assert server.combatants[0].hp == 13

def test_apply_heal_removes_down(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": 0, "conditions": ["Unconscious"]
    }})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert "Unconscious" not in server.combatants[0].conditions
    assert server.combatants[0].hp == 5

def test_apply_heal_zero_does_not_remove_down(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": 0, "conditions": ["Unconscious"]
    }})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 0})
    assert "Unconscious" in server.combatants[0].conditions

def test_apply_heal_none_hp_treated_as_zero(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": None
    }})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 10})
    assert server.combatants[0].hp == 10

def test_apply_heal_capped_at_max_hp(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": 8, "max_hp": 10
    }})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 10

def test_apply_heal_no_cap_without_max_hp(server):
    server.process_intent({"action": "add_combatant", "combatant": {
        "name": "A", "initiative": 10, "hp": 8
    }})
    server.process_intent({"action": "apply_heal", "name": "A", "amount": 5})
    assert server.combatants[0].hp == 13


# --- save / load roundtrip ---

def test_save_load_roundtrip(server, tmp_path):
    add(server, "A", 20)
    add(server, "B", 10)
    server.active_index = 1
    server.turn = 3

    path = str(tmp_path / "combat.json")
    server.process_intent({"action": "save", "path": path})

    s2 = GameServer()
    s2.process_intent({"action": "load", "path": path})

    assert len(s2.combatants) == 2
    assert s2.combatants[0].name == "A"
    assert s2.combatants[1].name == "B"
    assert s2.active_index == 1
    assert s2.turn == 3

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
