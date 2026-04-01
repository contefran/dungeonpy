import pytest
from unittest.mock import patch
from Core.combatant import Combatant
from Core.tracker import Tracker


def make(name, initiative, hp=10):
    return Combatant(name, initiative, hp=hp)


@pytest.fixture
def tracker():
    with patch('Core.tracker.SocketBridge'):
        t = Tracker()
    yield t


def make_tracker():
    with patch('Core.tracker.SocketBridge'):
        return Tracker()


# --- add / sort ---

def test_add_sorts_by_initiative(tracker):
    tracker.add(make("B", 5))
    tracker.add(make("A", 15))
    tracker.add(make("C", 10))
    assert [c.name for c in tracker.combatants] == ["A", "C", "B"]

def test_add_equal_initiative_stable(tracker):
    tracker.add(make("A", 10))
    tracker.add(make("B", 10))
    assert len(tracker.combatants) == 2


# --- next ---

def test_next_advances_index(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 0
    tracker.next()
    assert tracker.active_index == 1

def test_next_wraps_and_increments_turn(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 1
    tracker.turn = 1
    tracker.next()
    assert tracker.active_index == 0
    assert tracker.turn == 2

def test_next_returns_active(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    result = tracker.next()
    assert result == tracker.get_active()

def test_next_empty_returns_none(tracker):
    assert tracker.next() is None


# --- previous ---

def test_previous_retreats_index(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 1
    tracker.previous()
    assert tracker.active_index == 0

def test_previous_wraps_and_decrements_turn(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 0
    tracker.turn = 3
    tracker.previous()
    assert tracker.active_index == 1
    assert tracker.turn == 2

def test_previous_turn_floor_is_one(tracker):
    tracker.add(make("A", 20))
    tracker.active_index = 0
    tracker.turn = 1
    tracker.previous()
    assert tracker.turn == 1

def test_previous_empty_returns_none(tracker):
    assert tracker.previous() is None


# --- get_active ---

def test_get_active(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 1
    assert tracker.get_active().name == "B"

def test_get_active_empty(tracker):
    assert tracker.get_active() is None


# --- select_by_name ---

def test_select_by_name_found(tracker):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    c = tracker.select_by_name("B")
    assert c.name == "B"
    assert tracker.active_index == 1

def test_select_by_name_not_found(tracker):
    tracker.add(make("A", 20))
    assert tracker.select_by_name("Z") is None


# --- apply_damage ---

def test_apply_damage_reduces_hp(tracker):
    c = make("A", 10, hp=20)
    tracker.apply_damage(c, 5)
    assert c.hp == 15

def test_apply_damage_floors_at_zero(tracker):
    c = make("A", 10, hp=3)
    tracker.apply_damage(c, 10)
    assert c.hp == 0

def test_apply_damage_adds_down_at_zero(tracker):
    c = make("A", 10, hp=3)
    tracker.apply_damage(c, 10)
    assert "Down" in c.conditions

def test_apply_damage_no_duplicate_down(tracker):
    c = Combatant("A", 10, hp=3, conditions=["Down"])
    tracker.apply_damage(c, 10)
    assert c.conditions.count("Down") == 1

def test_apply_damage_partial_does_not_add_down(tracker):
    c = make("A", 10, hp=10)
    tracker.apply_damage(c, 5)
    assert "Down" not in c.conditions

def test_apply_damage_none_hp_treated_as_zero(tracker):
    c = Combatant("A", 10, hp=None)
    tracker.apply_damage(c, 5)
    assert c.hp == 0
    assert "Down" in c.conditions


# --- apply_heal ---

def test_apply_heal_increases_hp(tracker):
    c = make("A", 10, hp=5)
    tracker.apply_heal(c, 8)
    assert c.hp == 13

def test_apply_heal_removes_down(tracker):
    c = Combatant("A", 10, hp=0, conditions=["Down"])
    tracker.apply_heal(c, 5)
    assert "Down" not in c.conditions
    assert c.hp == 5

def test_apply_heal_zero_does_not_remove_down(tracker):
    c = Combatant("A", 10, hp=0, conditions=["Down"])
    tracker.apply_heal(c, 0)
    assert "Down" in c.conditions

def test_apply_heal_none_hp_treated_as_zero(tracker):
    c = Combatant("A", 10, hp=None)
    tracker.apply_heal(c, 10)
    assert c.hp == 10


# --- save / load roundtrip ---

def test_save_load_roundtrip(tracker, tmp_path):
    tracker.add(make("A", 20))
    tracker.add(make("B", 10))
    tracker.active_index = 1
    tracker.turn = 3

    path = str(tmp_path / "combat.json")
    tracker.save_to_file(path)

    t2 = make_tracker()
    t2.load_from_file(path)

    assert len(t2.combatants) == 2
    assert t2.combatants[0].name == "A"
    assert t2.combatants[1].name == "B"
    assert t2.active_index == 1
    assert t2.turn == 3

def test_load_replaces_existing_combatants(tracker, tmp_path):
    tracker.add(make("A", 20))
    path = str(tmp_path / "combat.json")
    tracker.save_to_file(path)

    t2 = make_tracker()
    t2.add(make("OldGuy", 99))
    t2.load_from_file(path)

    assert all(c.name != "OldGuy" for c in t2.combatants)
