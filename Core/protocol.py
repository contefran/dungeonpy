# Wire format for tracker <-> map messages.
# All constructors and parsing live here so both sides stay in sync.
# The string format is intentionally simple for now; step 3 of the roadmap
# will evolve this into JSON with sequence numbers.

CLEAR_SELECTION = "CLEAR_SELECTION"

TYPE_CLEAR    = "clear_selection"
TYPE_SELECTED = "selected"
TYPE_ACTIVE   = "active"


def make_selected(name: str) -> str:
    return f"{name} selected"

def make_active(name: str) -> str:
    return f"{name} active"


def parse(message: str) -> dict | None:
    """Return a dict with at least a 'type' key, or None for unknown messages."""
    if message == CLEAR_SELECTION:
        return {"type": TYPE_CLEAR}
    if message.endswith(" selected"):
        return {"type": TYPE_SELECTED, "name": message[: -len(" selected")]}
    if message.endswith(" active"):
        return {"type": TYPE_ACTIVE, "name": message[: -len(" active")]}
    return None
