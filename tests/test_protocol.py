import Core.protocol as proto


# --- constructors ---

def test_make_selected():
    assert proto.make_selected("Goblin") == "Goblin selected"

def test_make_active():
    assert proto.make_active("Rogue") == "Rogue active"

def test_make_selected_name_with_spaces():
    assert proto.make_selected("Dark Knight") == "Dark Knight selected"


# --- parse: clear ---

def test_parse_clear_selection():
    msg = proto.parse(proto.CLEAR_SELECTION)
    assert msg["type"] == proto.TYPE_CLEAR

# --- parse: selected ---

def test_parse_selected():
    msg = proto.parse("Goblin selected")
    assert msg["type"] == proto.TYPE_SELECTED
    assert msg["name"] == "Goblin"

def test_parse_selected_name_with_spaces():
    msg = proto.parse("Dark Knight selected")
    assert msg["type"] == proto.TYPE_SELECTED
    assert msg["name"] == "Dark Knight"

# --- parse: active ---

def test_parse_active():
    msg = proto.parse("Rogue active")
    assert msg["type"] == proto.TYPE_ACTIVE
    assert msg["name"] == "Rogue"

def test_parse_active_name_with_spaces():
    msg = proto.parse("Dark Knight active")
    assert msg["type"] == proto.TYPE_ACTIVE
    assert msg["name"] == "Dark Knight"

# --- parse: unknown ---

def test_parse_unknown_returns_none():
    assert proto.parse("some garbage") is None

def test_parse_empty_returns_none():
    assert proto.parse("") is None

# --- roundtrip ---

def test_roundtrip_selected():
    name = "Lich King"
    msg = proto.parse(proto.make_selected(name))
    assert msg["type"] == proto.TYPE_SELECTED
    assert msg["name"] == name

def test_roundtrip_active():
    name = "Lich King"
    msg = proto.parse(proto.make_active(name))
    assert msg["type"] == proto.TYPE_ACTIVE
    assert msg["name"] == name
