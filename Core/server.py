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
from Core.protocol import validate_intent, make_event, make_snapshot, make_error


class GameServer:

    def __init__(self, snapshot_interval: int = 50):
        self.combatants: list[Combatant] = []
        self.active_index: int = 0
        self.turn: int = 1
        self.door_states: dict[tuple, str] = {}         # (row, col) → 'open'|'closed'
        self.secret_door_states: dict[tuple, str] = {}  # (row, col) → 'open'|'closed'
        self._subscribers: list = []
        self._seq: int = 0
        self._snapshot_interval: int = snapshot_interval

    # ------------------------------------------------------------------
    # Pub/sub
    # ------------------------------------------------------------------

    def subscribe(self, callback):
        """Register a callback(event: dict) to receive all broadcast events."""
        self._subscribers.append(callback)

    def submit(self, intent: dict):
        """
        Submit an intent: validate → process → stamp seq → echo client_req_id
        → broadcast → maybe append periodic snapshot.
        """
        client_req_id = intent.get("client_req_id")

        ok, reason = validate_intent(intent)
        if not ok:
            self._seq += 1
            error = make_error(reason, self._seq, client_req_id)
            for cb in self._subscribers:
                cb(error)
            return

        raw_events = self.process_intent(intent)

        stamped: list[dict] = []
        for raw in raw_events:
            self._seq += 1
            if raw.get("type") == "snapshot":
                msg = make_snapshot(raw["state"], self._seq, client_req_id)
            else:
                fields = {k: v for k, v in raw.items() if k not in ("type", "action")}
                msg = make_event(raw["action"], self._seq, client_req_id, **fields)
            stamped.append(msg)

        # Periodic full snapshot: append one after the last stamped event
        # if _seq crossed a multiple of _snapshot_interval during this submit.
        if stamped and self._snapshot_interval > 0:
            if self._seq % self._snapshot_interval == 0:
                self._seq += 1
                stamped.append(make_snapshot(self.get_snapshot()["state"], self._seq))

        for cb in self._subscribers:
            for msg in stamped:
                cb(msg)

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
        """Return a raw snapshot dict (no seq stamp — stamping is done in submit())."""
        return {
            "type": "snapshot",
            "seq": self._seq,
            "state": {
                "combatants": [c.to_dict() for c in self.combatants],
                "active_index": self.active_index,
                "turn": self.turn,
                "door_states": {f"{r},{c}": v for (r, c), v in self.door_states.items()},
                "secret_door_states": {f"{r},{c}": v for (r, c), v in self.secret_door_states.items()},
            },
        }

    # ------------------------------------------------------------------
    # Damage / heal
    # ------------------------------------------------------------------

    def _apply_damage(self, combatant: Combatant, amount: int):
        current = combatant.hp if combatant.hp is not None else 0
        combatant.hp = max(0, current - amount)
        if combatant.hp == 0 and "Unconscious" not in combatant.conditions:
            combatant.conditions.append("Unconscious")

    def _apply_heal(self, combatant: Combatant, amount: int):
        current = combatant.hp if combatant.hp is not None else 0
        new_hp = current + amount
        if combatant.max_hp is not None:
            new_hp = min(new_hp, combatant.max_hp)
        combatant.hp = new_hp
        if combatant.hp > 0 and "Unconscious" in combatant.conditions:
            combatant.conditions.remove("Unconscious")

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def _next(self):
        if not self.combatants:
            return
        if all("Dead" in c.conditions for c in self.combatants):
            return
        n = len(self.combatants)
        while True:
            self.active_index = (self.active_index + 1) % n
            if self.active_index == 0:
                self.turn += 1
            if "Dead" not in self.combatants[self.active_index].conditions:
                break

    def _previous(self):
        if not self.combatants:
            return
        if all("Dead" in c.conditions for c in self.combatants):
            return
        n = len(self.combatants)
        while True:
            if self.active_index == 0:
                self.active_index = n - 1
                self.turn = max(1, self.turn - 1)
            else:
                self.active_index -= 1
            if "Dead" not in self.combatants[self.active_index].conditions:
                break

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
            events = [{"type": "event", "action": "turn_advanced",
                       "active": active.name if active else None, "turn": self.turn}]
            current_init = active.initiative if active else 0
            for c in self.combatants:
                if not c.condition_timers:
                    continue
                expired = []
                for cond, timing in list(c.condition_timers.items()):
                    exp_round, exp_init = timing
                    if self.turn > exp_round or (self.turn == exp_round and current_init <= exp_init):
                        expired.append(cond)
                if expired:
                    for cond in expired:
                        c.conditions = [x for x in c.conditions if x != cond]
                        del c.condition_timers[cond]
                    events.append({"type": "event", "action": "combatant_updated",
                                   "combatant": c.to_dict()})
            return events

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
                if "Dead" in c.conditions:
                    c.conditions = ["Dead"]
                    c.condition_timers = {}
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

        if action in ("move_up", "move_down"):
            name = intent.get("name")
            i = next((idx for idx, c in enumerate(self.combatants) if c.name == name), None)
            if i is None:
                return []
            j = i - 1 if action == "move_up" else i + 1
            if j < 0 or j >= len(self.combatants):
                return []
            if self.combatants[i].initiative != self.combatants[j].initiative:
                return []
            self.combatants[i], self.combatants[j] = self.combatants[j], self.combatants[i]
            if self.active_index == i:
                self.active_index = j
            elif self.active_index == j:
                self.active_index = i
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
