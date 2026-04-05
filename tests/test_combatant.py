from Core.combatant import Combatant


# --- is_down ---

def test_is_down_hp_zero():
    assert Combatant("Goblin", 10, hp=0).is_down()

def test_is_down_condition():
    assert Combatant("Goblin", 10, hp=5, conditions=["Unconscious"]).is_down()

def test_is_down_both():
    assert Combatant("Goblin", 10, hp=0, conditions=["Unconscious"]).is_down()

def test_is_down_false():
    assert not Combatant("Goblin", 10, hp=5).is_down()

def test_is_down_none_hp():
    assert not Combatant("Goblin", 10, hp=None).is_down()


# --- serialization roundtrip ---

def test_to_dict_from_dict_roundtrip():
    c = Combatant("Rogue", 21, hp=14, max_hp=20, conditions=["Invis"], pos=[1, 2], icon="rogue.png", notes="stealthy")
    c2 = Combatant.from_dict(c.to_dict())
    assert c2.name == "Rogue"
    assert c2.initiative == 21
    assert c2.hp == 14
    assert c2.max_hp == 20
    assert c2.conditions == ["Invis"]
    assert c2.pos == [1, 2]
    assert c2.icon == "rogue.png"
    assert c2.notes == "stealthy"

def test_from_dict_null_hp():
    c = Combatant.from_dict({"name": "Warrior", "initiative": 13, "hp": None})
    assert c.hp is None

def test_from_dict_defaults():
    c = Combatant.from_dict({"name": "X", "initiative": 5})
    assert c.hp is None
    assert c.max_hp is None
    assert c.conditions == []
    assert c.pos is None
    assert c.icon is None
    assert c.notes == ''
    assert c.is_pc is False

def test_is_pc_roundtrip():
    c = Combatant("Aragorn", 18, is_pc=True)
    c2 = Combatant.from_dict(c.to_dict())
    assert c2.is_pc is True

def test_is_pc_default_false():
    c = Combatant("Goblin", 8)
    assert c.is_pc is False
    assert Combatant.from_dict({"name": "G", "initiative": 8}).is_pc is False
