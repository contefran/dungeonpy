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
import os
from Core.combatant import Combatant
from Core.protocol import validate_intent, make_event, make_snapshot, make_error
from Core.los import compute_los


def _load_map_grid(filepath: str) -> list:
    """Parse a dungeon .txt file into a 2D list of ints."""
    def _parse(ch):
        if ch.isdigit():
            return int(ch)
        if ch.isalpha():
            return ord(ch.lower()) - ord('a') + 10
        return 0
    with open(filepath, 'r') as f:
        lines = f.readlines()
    return [[_parse(ch) for ch in line.strip()] for line in lines if line.strip()]


class GameServer:

    def __init__(self, snapshot_interval: int = 50):
        self.combatants: list[Combatant] = []
        self.active_index: int = 0
        self.turn: int = 1
        self.door_states: dict[tuple, str] = {}         # (row, col) → 'open'|'closed'  tile 3 wooden
        self.iron_door_states: dict[tuple, str] = {}    # (row, col) → 'open'|'closed'  tile 4 iron
        self.secret_door_states: dict[tuple, str] = {}  # (row, col) → 'open'|'closed'  tile 5 secret
        self.trap_states: dict[tuple, str] = {}          # (row, col) → 'open'|'closed'  tile 6 trap
        self.player_selection_locks: dict[str, bool] = {}  # player name → allowed to select
        self.player_move_locks: dict[str, bool] = {}       # player name → allowed to move token
        self.tile_highlights: list[dict] = []              # [{"pos":[c,r],"color":"gold","owner":"DM"}, ...]
        self.map_objects: list[dict] = []                  # [{"pos":[c,r],"icon":"chest.png","width":1,"height":1}, ...]
        self.light_sources: list[dict] = []               # [{"pos":[c,r],"radius":4,"color":"warm"}, ...]
        self.map_grid: list | None = None                # 2-D tile grid; included in snapshots
        self.map_path: str | None = None                 # absolute path to the loaded .txt map file
        self.map_visible: bool = False                   # whether the map window is shown to everyone
        self.visibility_radius: int = 10                 # LOS radius in tiles (DM-configurable)
        self.explored_tiles: dict[str, set] = {}         # {player_name: {(col,row), ...}}
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

    def get_snapshot(self, player_name: str | None = None) -> dict:
        """
        Return a raw snapshot dict (no seq stamp — stamping is done in submit()).

        If *player_name* is given, explored_tiles contains only that player's data.
        Secret doors are sent as tile-5 to all clients; fog-of-war is enforced
        client-side via _player_secret_door_states.
        """
        state = {
            "combatants": [c.to_dict() for c in self.combatants],
            "active_index": self.active_index,
            "turn": self.turn,
            "door_states": {f"{r},{c}": v for (r, c), v in self.door_states.items()},
            "iron_door_states": {f"{r},{c}": v for (r, c), v in self.iron_door_states.items()},
            "secret_door_states": {f"{r},{c}": v for (r, c), v in self.secret_door_states.items()},
            "trap_states": {f"{r},{c}": v for (r, c), v in self.trap_states.items()},
            "player_selection_locks": dict(self.player_selection_locks),
            "player_move_locks": dict(self.player_move_locks),
            "map_grid": self.map_grid,
            "map_path": self.map_path,
            "map_visible": self.map_visible,
            "tile_highlights": list(self.tile_highlights),
            "map_objects": list(self.map_objects),
            "light_sources": list(self.light_sources),
            "visibility_radius": self.visibility_radius,
            "explored_tiles": [list(t) for t in self.explored_tiles.get(player_name, set())]
                               if player_name else {},
        }
        return {"type": "snapshot", "seq": self._seq, "state": state}

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
        self.map_path = data.get("map_path")
        self.map_visible = False  # always start hidden on session resume
        self.visibility_radius = data.get("visibility_radius", 10)
        self.map_objects = list(data.get("map_objects", []))
        self.light_sources = list(data.get("light_sources", []))
        self.explored_tiles = {
            name: {tuple(t) for t in tiles}
            for name, tiles in data.get("explored_tiles", {}).items()
        }
        if self.map_path and os.path.isfile(self.map_path):
            self.map_grid = _load_map_grid(self.map_path)
        else:
            self.map_grid = None

    def save_to_file(self, filepath: str):
        data = {
            "initiative": [c.to_dict() for c in self.combatants],
            "active_index": self.active_index,
            "turn": self.turn,
            "map_path": self.map_path,
            "visibility_radius": self.visibility_radius,
            "map_objects": list(self.map_objects),
            "light_sources": list(self.light_sources),
            "explored_tiles": {
                name: [list(t) for t in tiles]
                for name, tiles in self.explored_tiles.items()
            },
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

    # ------------------------------------------------------------------
    # LOS / explored tiles helpers
    # ------------------------------------------------------------------

    def _update_explored(self, name: str, pos) -> list[dict]:
        """
        Compute LOS from *pos*, add newly visible tiles to explored_tiles[name],
        and return a targeted explored_updated event if any new tiles were found.
        """
        if not self.map_grid or not pos:
            return []
        c = self._get(name)
        size = c.size if c else 1
        los_origin = [pos[0] + size // 2, pos[1] + size // 2] if size > 1 else pos
        los = compute_los(
            self.map_grid, los_origin, self.visibility_radius,
            self.door_states, self.iron_door_states, self.secret_door_states,
        )
        already = self.explored_tiles.get(name, set())
        new_tiles = los - already
        if not new_tiles:
            return []
        self.explored_tiles.setdefault(name, set()).update(new_tiles)
        return [{"type": "event", "action": "explored_updated",
                 "target": name,
                 "new_tiles": [list(t) for t in new_tiles]}]

    # ------------------------------------------------------------------
    # Intent processing — the single entry point for all state changes
    # ------------------------------------------------------------------

    def process_intent(self, intent: dict) -> list[dict]:
        action = intent.get("action")

        # --- Selection ---
        if action == "select":
            name = intent.get("name")
            if self._get(name):
                event = {"type": "event", "action": "selection_changed", "name": name}
                if "selector" in intent:
                    event["selector"] = intent["selector"]
                    event["color"] = intent.get("color", "white")
                return [event]
            return []

        if action == "clear_selection":
            event = {"type": "event", "action": "selection_cleared"}
            if "selector" in intent:
                event["selector"] = intent["selector"]
            return [event]

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
                events = [{"type": "event", "action": "token_placed", "name": name, "pos": pos}]
                events += self._update_explored(name, pos)
                return events
            return []

        if action == "move_token":
            name, pos = intent.get("name"), intent.get("pos")
            c = self._get(name)
            if c:
                c.pos = pos
                events = [{"type": "event", "action": "token_moved", "name": name, "pos": pos}]
                events += self._update_explored(name, pos)
                return events
            return []

        # --- Map: doors ---
        if action == "toggle_door":
            x, y, tile_type = intent.get("x"), intent.get("y"), intent.get("tile_type", 3)
            key = (y, x)
            if tile_type == 4:
                states = self.iron_door_states
            elif tile_type == 5:
                states = self.secret_door_states
            elif tile_type == 6:
                states = self.trap_states
            else:
                states = self.door_states
            new = "open" if states.get(key, "closed") == "closed" else "closed"
            states[key] = new
            return [{"type": "event", "action": "door_toggled",
                     "x": x, "y": y, "tile_type": tile_type, "state": new}]

        # --- Player management ---
        if action == "set_player_lock":
            name = intent.get("name")
            lock_type = intent.get("lock_type", "move")  # "select" or "move"
            locked = bool(intent.get("locked", False))
            if lock_type == "select":
                self.player_selection_locks[name] = locked
                events = [{"type": "event", "action": "player_lock_changed",
                           "name": name, "lock_type": "select", "locked": locked}]
                if not locked:
                    events.append({"type": "event", "action": "selection_cleared",
                                   "selector": name})
                    self.tile_highlights = [h for h in self.tile_highlights if h["owner"] != name]
                    events.append({"type": "event", "action": "highlights_changed",
                                   "highlights": list(self.tile_highlights)})
                return events
            else:
                self.player_move_locks[name] = locked
                return [{"type": "event", "action": "player_lock_changed",
                         "name": name, "lock_type": "move", "locked": locked}]

        if action == "player_connected":
            name  = intent.get("name")
            color = intent.get("color", "white")
            self.player_selection_locks.setdefault(name, False)
            self.player_move_locks.setdefault(name, False)
            return [{"type": "event", "action": "player_connected", "name": name, "color": color}]

        if action == "player_disconnected":
            name = intent.get("name")
            self.player_selection_locks.pop(name, None)
            self.player_move_locks.pop(name, None)
            return [{"type": "event", "action": "player_disconnected", "name": name}]

        # --- Map lifecycle ---
        if action == "load_map":
            path = intent.get("path")
            if not path or not os.path.isfile(path):
                return []
            self.map_path = path
            self.map_grid = _load_map_grid(path)
            # Keep PCs only, reset their state for the new map
            self.combatants = [c for c in self.combatants if c.is_pc]
            for c in self.combatants:
                c.initiative = 1
                c.pos = None
            self.active_index = 0
            self.turn = 1
            self.door_states = {}
            self.iron_door_states = {}
            self.secret_door_states = {}
            self.trap_states = {}
            self.tile_highlights = []
            self.map_objects = []
            self.light_sources = []
            self.explored_tiles = {}
            self.map_visible = True  # auto-open so DM can place tokens
            return [
                {"type": "event", "action": "map_loaded", "path": path},
                self.get_snapshot(),
            ]

        if action == "set_map_visible":
            visible = bool(intent.get("visible", False))
            self.map_visible = visible
            return [{"type": "event", "action": "map_visibility_changed", "visible": visible}]

        # --- Tile highlights ---
        if action == "highlight_tile":
            pos   = intent.get("pos")
            color = intent.get("color", "gold")
            owner = intent.get("owner", "DM")
            existing = next((h for h in self.tile_highlights
                             if h["pos"] == pos and h["owner"] == owner), None)
            if existing:
                self.tile_highlights.remove(existing)
            else:
                self.tile_highlights.append({"pos": pos, "color": color, "owner": owner})
            return [{"type": "event", "action": "highlights_changed",
                     "highlights": list(self.tile_highlights)}]

        if action == "clear_highlights":
            owner = intent.get("owner", "DM")
            self.tile_highlights = [h for h in self.tile_highlights if h["owner"] != owner]
            return [{"type": "event", "action": "highlights_changed",
                     "highlights": list(self.tile_highlights)}]

        if action == "add_map_object":
            pos    = intent.get("pos")
            icon   = intent.get("icon")
            width  = max(1, int(intent.get("width",  intent.get("size", 1))))
            height = max(1, int(intent.get("height", intent.get("size", 1))))
            if pos and icon:
                obj = {"pos": pos, "icon": icon, "width": width, "height": height}
                self.map_objects.append(obj)
                return [{"type": "event", "action": "map_object_added", "object": obj}]
            return []

        if action == "remove_map_object":
            pos = intent.get("pos")  # top-left corner of the object to remove
            before = len(self.map_objects)
            self.map_objects = [o for o in self.map_objects if o["pos"] != pos]
            if len(self.map_objects) < before:
                return [{"type": "event", "action": "map_object_removed", "pos": pos}]
            return []

        if action == "add_light_source":
            pos    = intent.get("pos")
            radius = max(1, int(intent.get("radius", 4)))
            color  = intent.get("color", "warm")
            alpha  = max(0, min(255, int(intent.get("alpha", 60))))
            if pos:
                ls = {"pos": pos, "radius": radius, "color": color, "alpha": alpha}
                self.light_sources.append(ls)
                return [{"type": "event", "action": "light_source_added", "light": ls}]
            return []

        if action == "remove_light_source":
            pos = intent.get("pos")
            before = len(self.light_sources)
            self.light_sources = [ls for ls in self.light_sources if ls["pos"] != pos]
            if len(self.light_sources) < before:
                return [{"type": "event", "action": "light_source_removed", "pos": pos}]
            return []

        if action == "recenter_all":
            pos = intent.get("pos")
            if pos:
                return [{"type": "event", "action": "recenter_all", "pos": pos}]
            return []

        if action == "set_visibility_radius":
            r = int(intent.get("radius", 10))
            r = max(1, min(r, 30))
            self.visibility_radius = r
            return [{"type": "event", "action": "visibility_radius_changed", "radius": r}]

        # --- Chat ---
        if action == "chat_message":
            text = intent.get("text", "").strip()
            if not text:
                return []
            return [{"type": "event", "action": "chat_message",
                     "from": intent.get("from", "DM"),
                     "to":   intent.get("to"),
                     "text": text}]

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
