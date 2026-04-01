"""
Authoritative game server — owns all canonical state.

Phase A: pure state machine, no networking.
Clients submit intents (dicts); the server validates, mutates state, and
returns a list of event/snapshot dicts to be broadcast.

Intent  (client → server): {"action": "...", ...fields}
Event   (server → client): {"type": "event",    "action": "...", ...fields}
Snapshot(server → client): {"type": "snapshot", "state": {...}}
"""

import json
from Core.combatant import Combatant


class GameServer:

    def __init__(self):
        self.combatants: list[Combatant] = []
        self.active_index: int = 0
        self.turn: int = 1
        self.door_states: dict[tuple, str] = {}         # (row, col) → 'open'|'closed'
        self.secret_door_states: dict[tuple, str] = {}  # (row, col) → 'open'|'closed'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get(self, name: str) -> Combatant | None:
        for c in self.combatants:
            if c.name == name:
                return c
        return None

    def _sort(self):
        active = self.get_active()
        self.combatants.sort(key=lambda c: c.initiative, reverse=True)
        # Keep active_index pointing at the same combatant after a sort
        if active:
            for i, c in enumerate(self.combatants):
                if c is active:
                    self.active_index = i
                    break

    def get_active(self) -> Combatant | None:
        if 0 <= self.active_index < len(self.combatants):
            return self.combatants[self.active_index]
        return None

    def get_snapshot(self) -> dict:
        return {
            "type": "snapshot",
            "state": {
                "combatants": [c.to_dict() for c in self.combatants],
                "active_index": self.active_index,
                "turn": self.turn,
                "door_states": {f"{r},{c}": v for (r, c), v in self.door_states.items()},
                "secret_door_states": {f"{r},{c}": v for (r, c), v in self.secret_door_states.items()},
            },
        }

    # ------------------------------------------------------------------
    # Damage / heal  (same logic as Tracker, now lives here canonically)
    # ------------------------------------------------------------------

    def _apply_damage(self, combatant: Combatant, amount: int):
        current = combatant.hp if combatant.hp is not None else 0
        combatant.hp = max(0, current - amount)
        if combatant.hp == 0 and "Down" not in combatant.conditions:
            combatant.conditions.append("Down")

    def _apply_heal(self, combatant: Combatant, amount: int):
        current = combatant.hp if combatant.hp is not None else 0
        combatant.hp = current + amount
        if combatant.hp > 0 and "Down" in combatant.conditions:
            combatant.conditions.remove("Down")

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def _next(self):
        if not self.combatants:
            return
        self.active_index = (self.active_index + 1) % len(self.combatants)
        if self.active_index == 0:
            self.turn += 1

    def _previous(self):
        if not self.combatants:
            return
        if self.active_index == 0:
            self.active_index = len(self.combatants) - 1
            self.turn = max(1, self.turn - 1)
        else:
            self.active_index -= 1

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_from_file(self, filepath: str):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.combatants = [Combatant.from_dict(c) for c in data.get("initiative", [])]
        self.active_index = data.get("active_index", 0)
        self.turn = data.get("turn", 1)

    def save_to_file(self, filepath: str):
        data = {
            "initiative": [c.to_dict() for c in self.combatants],
            "active_index": self.active_index,
            "turn": self.turn,
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # Intent processing — the single entry point for all state changes
    # ------------------------------------------------------------------

    def process_intent(self, intent: dict) -> list[dict]:
        action = intent.get("action")

        # --- Selection ---
        if action == "select":
            name = intent.get("name")
            if self._get(name):
                return [{"type": "event", "action": "selection_changed", "name": name}]
            return []

        if action == "clear_selection":
            return [{"type": "event", "action": "selection_cleared"}]

        # --- Turn ---
        if action == "advance_turn":
            self._next()
            active = self.get_active()
            return [{"type": "event", "action": "turn_advanced",
                     "active": active.name if active else None, "turn": self.turn}]

        if action == "retreat_turn":
            self._previous()
            active = self.get_active()
            return [{"type": "event", "action": "turn_advanced",
                     "active": active.name if active else None, "turn": self.turn}]

        # --- HP ---
        if action == "apply_damage":
            c = self._get(intent.get("name"))
            if c:
                self._apply_damage(c, intent.get("amount", 0))
                return [{"type": "event", "action": "combatant_updated", "combatant": c.to_dict()}]
            return []

        if action == "apply_heal":
            c = self._get(intent.get("name"))
            if c:
                self._apply_heal(c, intent.get("amount", 0))
                return [{"type": "event", "action": "combatant_updated", "combatant": c.to_dict()}]
            return []

        # --- Combatant list ---
        if action == "add_combatant":
            c = Combatant.from_dict(intent.get("combatant", {}))
            self.combatants.append(c)
            self._sort()
            return [{"type": "event", "action": "combatant_added", "combatant": c.to_dict()}]

        if action == "update_combatant":
            c = self._get(intent.get("name"))
            if c:
                fields = intent.get("fields", {})
                initiative_changed = "initiative" in fields and fields["initiative"] != c.initiative
                for key, value in fields.items():
                    if hasattr(c, key):
                        setattr(c, key, value)
                if initiative_changed:
                    self._sort()
                    return [self.get_snapshot()]
                return [{"type": "event", "action": "combatant_updated", "combatant": c.to_dict()}]
            return []

        if action == "delete_combatant":
            name = intent.get("name")
            for i, c in enumerate(self.combatants):
                if c.name == name:
                    self.combatants.pop(i)
                    if not self.combatants:
                        self.active_index = 0
                    elif i == self.active_index:
                        self.active_index = min(self.active_index, len(self.combatants) - 1)
                    elif i < self.active_index:
                        self.active_index -= 1
                    return [{"type": "event", "action": "combatant_removed", "name": name}]
            return []

        if action == "move_up":
            name = intent.get("name")
            for i, c in enumerate(self.combatants):
                if c.name == name and i > 0:
                    self.combatants[i], self.combatants[i - 1] = self.combatants[i - 1], self.combatants[i]
                    if i == self.active_index:
                        self.active_index -= 1
                    elif i - 1 == self.active_index:
                        self.active_index += 1
                    break
            return [self.get_snapshot()]

        if action == "move_down":
            name = intent.get("name")
            for i, c in enumerate(self.combatants):
                if c.name == name and i < len(self.combatants) - 1:
                    self.combatants[i], self.combatants[i + 1] = self.combatants[i + 1], self.combatants[i]
                    if i == self.active_index:
                        self.active_index += 1
                    elif i + 1 == self.active_index:
                        self.active_index -= 1
                    break
            return [self.get_snapshot()]

        # --- Map: tokens ---
        if action == "place_token":
            name, pos = intent.get("name"), intent.get("pos")
            c = self._get(name)
            if c:
                c.pos = pos
                return [{"type": "event", "action": "token_placed", "name": name, "pos": pos}]
            return []

        if action == "move_token":
            name, pos = intent.get("name"), intent.get("pos")
            c = self._get(name)
            if c:
                c.pos = pos
                return [{"type": "event", "action": "token_moved", "name": name, "pos": pos}]
            return []

        # --- Map: doors ---
        if action == "toggle_door":
            x, y, tile_type = intent.get("x"), intent.get("y"), intent.get("tile_type", 3)
            key = (y, x)
            states = self.secret_door_states if tile_type == 4 else self.door_states
            new = "open" if states.get(key, "closed") == "closed" else "closed"
            states[key] = new
            return [{"type": "event", "action": "door_toggled",
                     "x": x, "y": y, "tile_type": tile_type, "state": new}]

        # --- Persistence ---
        if action == "save":
            path = intent.get("path")
            if path:
                self.save_to_file(path)
            return []

        if action == "load":
            path = intent.get("path")
            if path:
                self.load_from_file(path)
            return [self.get_snapshot()]

        return []  # unknown intent — ignored
