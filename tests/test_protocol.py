import pytest
from Core.protocol import (
    validate_intent,
    make_event,
    make_snapshot,
    make_error,
    INTENTS,
)
from Core.server import GameServer


# ---------------------------------------------------------------------------
# validate_intent
# ---------------------------------------------------------------------------


def test_validate_known_action_no_required_fields():
    ok, err = validate_intent({"action": "advance_turn"})
    assert ok and err is None


def test_validate_known_action_with_required_fields():
    ok, err = validate_intent({"action": "apply_damage", "name": "A", "amount": 5})
    assert ok and err is None


def test_validate_missing_required_field():
    ok, err = validate_intent({"action": "apply_damage", "name": "A"})  # missing amount
    assert not ok
    assert "amount" in err


def test_validate_unknown_action():
    ok, err = validate_intent({"action": "fly_away"})
    assert not ok
    assert "fly_away" in err


def test_validate_missing_action():
    ok, err = validate_intent({"name": "A"})
    assert not ok
    assert "action" in err


def test_validate_non_dict():
    ok, err = validate_intent("advance_turn")
    assert not ok


def test_validate_all_known_actions_have_schema():
    """Every action in INTENTS validates with its required fields present."""
    for action, required in INTENTS.items():
        intent = {"action": action}
        for field in required:
            intent[field] = "placeholder"
        ok, err = validate_intent(intent)
        assert ok, f"action '{action}' failed: {err}"


# ---------------------------------------------------------------------------
# make_event / make_snapshot / make_error factories
# ---------------------------------------------------------------------------


def test_make_event_has_correct_fields():
    e = make_event("turn_advanced", seq=3, active="Hero", turn=2)
    assert e == {
        "type": "event",
        "action": "turn_advanced",
        "seq": 3,
        "active": "Hero",
        "turn": 2,
    }


def test_make_event_includes_client_req_id():
    e = make_event("turn_advanced", seq=1, client_req_id="abc123")
    assert e["client_req_id"] == "abc123"


def test_make_event_omits_client_req_id_when_none():
    e = make_event("turn_advanced", seq=1)
    assert "client_req_id" not in e


def test_make_snapshot_structure():
    state = {"combatants": [], "active_index": 0, "turn": 1}
    s = make_snapshot(state, seq=7)
    assert s == {"type": "snapshot", "seq": 7, "state": state}


def test_make_snapshot_includes_client_req_id():
    s = make_snapshot({}, seq=2, client_req_id="xyz")
    assert s["client_req_id"] == "xyz"


def test_make_error_structure():
    e = make_error("unknown action 'foo'", seq=4)
    assert e == {"type": "error", "seq": 4, "reason": "unknown action 'foo'"}


def test_make_error_includes_client_req_id():
    e = make_error("bad", seq=1, client_req_id="req-99")
    assert e["client_req_id"] == "req-99"


# ---------------------------------------------------------------------------
# GameServer.submit — seq stamping
# ---------------------------------------------------------------------------


@pytest.fixture
def server():
    return GameServer()


def test_submit_stamps_seq_starting_at_one(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "advance_turn"})
    assert received[0]["seq"] == 1


def test_submit_seq_increments_per_event(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "advance_turn"})  # seq=1
    server.submit({"action": "advance_turn"})  # seq=2
    seqs = [m["seq"] for m in received]
    assert seqs == [1, 2]


def test_submit_multi_event_intent_uses_consecutive_seqs(server):
    """update_combatant with initiative change returns a snapshot; seq numbers must be consecutive."""
    received = []
    server.subscribe(received.append)
    server.submit(
        {"action": "add_combatant", "combatant": {"name": "A", "initiative": 10}}
    )
    server.submit(
        {"action": "add_combatant", "combatant": {"name": "B", "initiative": 5}}
    )
    received.clear()
    server.submit(
        {"action": "update_combatant", "name": "B", "fields": {"initiative": 20}}
    )
    seqs = [m["seq"] for m in received]
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs)))


# ---------------------------------------------------------------------------
# GameServer.submit — client_req_id echo
# ---------------------------------------------------------------------------


def test_submit_echoes_client_req_id(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "advance_turn", "client_req_id": "req-1"})
    assert received[0]["client_req_id"] == "req-1"


def test_submit_no_client_req_id_field_absent(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "advance_turn"})
    assert "client_req_id" not in received[0]


def test_submit_echoes_client_req_id_on_snapshot(server, tmp_path):
    path = str(tmp_path / "empty.json")
    import json

    open(path, "w").write(json.dumps({"initiative": [], "active_index": 0, "turn": 1}))
    received = []
    server.subscribe(received.append)
    server.submit({"action": "load", "path": path, "client_req_id": "snap-req"})
    snapshots = [m for m in received if m["type"] == "snapshot"]
    assert snapshots[0].get("client_req_id") == "snap-req"


# ---------------------------------------------------------------------------
# GameServer.submit — invalid intent → error event
# ---------------------------------------------------------------------------


def test_submit_unknown_action_broadcasts_error(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "bad_action"})
    assert len(received) == 1
    assert received[0]["type"] == "error"
    assert "bad_action" in received[0]["reason"]


def test_submit_missing_required_field_broadcasts_error(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "apply_damage", "name": "X"})  # missing amount
    assert received[0]["type"] == "error"


def test_submit_error_echoes_client_req_id(server):
    received = []
    server.subscribe(received.append)
    server.submit({"action": "bad_action", "client_req_id": "err-req"})
    assert received[0]["client_req_id"] == "err-req"


def test_submit_invalid_intent_does_not_change_state(server):
    server.submit(
        {"action": "add_combatant", "combatant": {"name": "A", "initiative": 10}}
    )
    server.submit({"action": "bad_action"})
    assert len(server.combatants) == 1


# ---------------------------------------------------------------------------
# Periodic snapshots
# ---------------------------------------------------------------------------


def test_periodic_snapshot_fires_at_interval(server):
    """With interval=3, after 3 events a snapshot should be appended."""
    server._snapshot_interval = 3
    received = []
    server.subscribe(received.append)

    # Each add_combatant emits 1 event; after 3 events seq==3 → snapshot appended
    for i in range(3):
        server.submit(
            {"action": "add_combatant", "combatant": {"name": str(i), "initiative": i}}
        )

    snapshots = [m for m in received if m["type"] == "snapshot"]
    assert len(snapshots) == 1


def test_periodic_snapshot_has_seq_after_last_event(server):
    server._snapshot_interval = 2
    received = []
    server.subscribe(received.append)

    server.submit({"action": "advance_turn"})  # seq=1
    server.submit({"action": "advance_turn"})  # seq=2 → periodic snapshot at seq=3

    snapshots = [m for m in received if m["type"] == "snapshot"]
    assert snapshots[-1]["seq"] == 3


def test_no_periodic_snapshot_before_interval(server):
    server._snapshot_interval = 10
    received = []
    server.subscribe(received.append)

    for _ in range(5):
        server.submit({"action": "advance_turn"})

    snapshots = [m for m in received if m["type"] == "snapshot"]
    assert len(snapshots) == 0


def test_periodic_snapshot_disabled_when_interval_zero():
    server = GameServer(snapshot_interval=0)
    received = []
    server.subscribe(received.append)

    for _ in range(100):
        server.submit({"action": "advance_turn"})

    snapshots = [m for m in received if m["type"] == "snapshot"]
    assert len(snapshots) == 0
