"""
DungeonPy wire protocol — schema definitions and message factories.

Intent  (client → server): {"action": "...", ...fields, "client_req_id": optional}
Event   (server → client): {"type": "event",    "action": "...", "seq": int, ...fields}
Snapshot(server → client): {"type": "snapshot", "seq": int, "state": {...}}
Error   (server → client): {"type": "error",    "seq": int, "reason": str, "client_req_id": optional}
"""

# ---------------------------------------------------------------------------
# Intent schema
# Each key is a valid action name; value is the list of required fields.
# ---------------------------------------------------------------------------

INTENTS: dict[str, list[str]] = {
    "add_combatant":    ["combatant"],
    "update_combatant": ["name", "fields"],
    "delete_combatant": ["name"],
    "move_up":          ["name"],
    "move_down":        ["name"],
    "apply_damage":     ["name", "amount"],
    "apply_heal":       ["name", "amount"],
    "advance_turn":     [],
    "retreat_turn":     [],
"select":           ["name"],
    "clear_selection":  [],
    "place_token":      ["name", "pos"],
    "move_token":       ["name", "pos"],
    "toggle_door":      ["x", "y"],
    "save":             ["path"],
    "load":             ["path"],
    "set_player_lock":      ["name", "lock_type", "locked"],
    "player_connected":     ["name"],
    "player_disconnected":  ["name"],
    "load_map":             ["path"],
    "set_map_visible":      ["visible"],
    "chat_message":         ["text"],
    "highlight_tile":       ["pos"],   # color/owner injected by bridge for players
    "clear_highlights":     ["owner"],
    "recenter_all":         ["pos"],   # DM only — broadcast view recenter to all players
    "set_visibility_radius": ["radius"],  # DM only
    "add_map_object":       ["pos", "icon", "width", "height"],  # DM only
    "remove_map_object":    ["pos"],                  # DM only — pos is the object's top-left
    "add_light_source":     ["pos", "radius", "color"],  # DM only
    "remove_light_source":  ["pos"],                  # DM only
    "aoe_add":    ["anchor", "shape", "size", "angle", "aperture", "color"],  # DM only
    "aoe_remove": ["id"],                             # DM only
}


def validate_intent(intent: dict) -> tuple[bool, str | None]:
    """Return (True, None) if the intent is valid, else (False, reason)."""
    if not isinstance(intent, dict):
        return False, "intent must be a dict"

    action = intent.get("action")
    if action is None:
        return False, "missing 'action' field"

    if action not in INTENTS:
        return False, f"unknown action '{action}'"

    for field in INTENTS[action]:
        if field not in intent:
            return False, f"action '{action}' requires field '{field}'"

    return True, None


# ---------------------------------------------------------------------------
# Message factories
# ---------------------------------------------------------------------------

def make_event(action: str, seq: int, client_req_id=None, **fields) -> dict:
    """Build a server-to-client event message."""
    msg = {"type": "event", "action": action, "seq": seq}
    if client_req_id is not None:
        msg["client_req_id"] = client_req_id
    msg.update(fields)
    return msg


def make_snapshot(state: dict, seq: int, client_req_id=None) -> dict:
    """Build a full-state snapshot message."""
    msg = {"type": "snapshot", "seq": seq, "state": state}
    if client_req_id is not None:
        msg["client_req_id"] = client_req_id
    return msg


def make_error(reason: str, seq: int, client_req_id=None) -> dict:
    """Build an error message."""
    msg = {"type": "error", "seq": seq, "reason": reason}
    if client_req_id is not None:
        msg["client_req_id"] = client_req_id
    return msg
