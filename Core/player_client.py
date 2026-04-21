"""
player_client.py — Remote player connection for DungeonPy.

Runs on the player's machine.  Connects to the DM's WSBridge over wss://,
performs the hello handshake, and then:
  - Incoming events/snapshots → applied to a local GameServer mirror so that
    MapManager can read state as if it were talking to a local server.
  - Outgoing intents from MapManager → forwarded to the DM server over WebSocket.

Initial connection: up to 10 attempts with 5 s back-off, then gives up.
After a successful handshake, reconnects indefinitely on drop (5 s back-off).
"""

import asyncio
import json
import threading

import websockets

from Core.combatant import Combatant


class PlayerClient:

    def __init__(self, server, host: str, port: int, name: str,
                 color: str = "white", ssl_context=None):
        self.server = server          # local GameServer mirror (read by MapManager)
        self.host = host
        self.port = port
        self.name = name
        self.color = color
        self._ssl_context = ssl_context
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws = None               # current live WebSocket (None when disconnected)
        self._running = True

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        """
        Start the reconnect loop in a daemon thread.
        Blocks until the first successful handshake or all initial attempts are exhausted.
        Check ``_running`` after this returns to know whether connection succeeded.
        """
        ready = threading.Event()
        threading.Thread(
            target=self._run, args=(ready,), daemon=True, name='player-client'
        ).start()
        ready.wait()  # no timeout — unblocked by success or permanent failure

    def _run(self, ready: threading.Event):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._reconnect_loop(ready))

    def stop(self):
        self._running = False

    # ------------------------------------------------------------------
    # Reconnect loop
    # ------------------------------------------------------------------

    _MAX_INITIAL_TRIES = 10

    async def _reconnect_loop(self, ready: threading.Event):
        scheme = "wss" if self._ssl_context else "ws"
        host = f"[{self.host}]" if ":" in self.host else self.host
        url = f"{scheme}://{host}:{self.port}"
        first = True
        initial_tries = 0

        while self._running:
            try:
                print(f"[PlayerClient] Connecting to {url} ...")
                async with websockets.connect(url, ssl=self._ssl_context) as ws:
                    self._ws = ws

                    # Handshake
                    await ws.send(json.dumps({
                        "type": "hello", "role": "player", "name": self.name,
                        "color": self.color,
                    }))
                    ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10.0))
                    if not ack.get("ok"):
                        print(f"[PlayerClient] Rejected: {ack.get('reason')}")
                        self._running = False
                        break

                    print(f"[PlayerClient] Connected as '{self.name}'.")
                    if first:
                        ready.set()
                        first = False
                        initial_tries = 0   # reset — we're in a live session now

                    # Normal receive loop
                    async for raw in ws:
                        self._apply_event(json.loads(raw))

            except Exception as e:
                self._ws = None
                if not self._running:
                    break
                if first:
                    initial_tries += 1
                    if initial_tries >= self._MAX_INITIAL_TRIES:
                        print(f"[PlayerClient] Could not reach {url} after "
                              f"{self._MAX_INITIAL_TRIES} attempts — giving up.")
                        self._running = False
                        break
                    print(f"[PlayerClient] Attempt {initial_tries}/{self._MAX_INITIAL_TRIES} "
                          f"failed ({e}) — retrying in 5 s ...")
                else:
                    print(f"[PlayerClient] Disconnected ({e}) — reconnecting in 5 s ...")
                await asyncio.sleep(5)

        if first:
            ready.set()  # unblock main thread even on immediate failure

    # ------------------------------------------------------------------
    # Apply incoming server event to the local mirror
    # ------------------------------------------------------------------

    def _apply_event(self, event: dict):
        """
        Update the mirror's state, then notify all subscribers (e.g. MapManager).
        Must be called on the asyncio thread only.
        """
        if event.get("type") == "snapshot":
            self._apply_snapshot(event["state"])
        else:
            self._apply_incremental(event)

        for cb in self.server._subscribers:
            try:
                cb(event)
            except Exception as e:
                print(f"[PlayerClient] Subscriber error: {e}")

    def _apply_snapshot(self, state: dict):
        self.server.combatants = [Combatant.from_dict(c)
                                   for c in state.get("combatants", [])]
        self.server.active_index = state.get("active_index", 0)
        self.server.turn = state.get("turn", 1)
        self.server.door_states = self._parse_key_dict(state.get("door_states", {}))
        self.server.iron_door_states = self._parse_key_dict(state.get("iron_door_states", {}))
        self.server.secret_door_states = self._parse_key_dict(state.get("secret_door_states", {}))
        self.server.trap_states = self._parse_key_dict(state.get("trap_states", {}))
        self.server.player_selection_locks = dict(state.get("player_selection_locks", {}))
        self.server.player_move_locks = dict(state.get("player_move_locks", {}))
        self.server.map_path = state.get("map_path")
        self.server.map_visible = state.get("map_visible", False)
        self.server.tile_highlights = list(state.get("tile_highlights", []))
        self.server.map_objects = list(state.get("map_objects", []))
        self.server.light_sources = list(state.get("light_sources", []))
        self.server.aoe_areas = list(state.get("aoe_areas", []))
        self.server.player_aoe_locks = dict(state.get("player_aoe_locks", {}))
        self.server.visibility_radius = state.get("visibility_radius", 10)
        self.server.explored_tiles = {
            self.name: {tuple(t) for t in state.get("explored_tiles", [])}
        }
        if state.get("map_grid"):
            self.server.map_grid = state["map_grid"]

    @staticmethod
    def _parse_key_dict(d: dict) -> dict:
        """Convert {"r,c": state} snapshot format back to {(r, c): state}."""
        out = {}
        for k, v in d.items():
            r, c = k.split(",")
            out[(int(r), int(c))] = v
        return out

    def _apply_incremental(self, event: dict):
        """Apply a single non-snapshot event to the mirror."""
        action = event.get("action")

        if action == "combatant_updated":
            new = Combatant.from_dict(event["combatant"])
            for i, c in enumerate(self.server.combatants):
                if c.name == new.name:
                    self.server.combatants[i] = new
                    break

        elif action == "combatant_added":
            c = Combatant.from_dict(event["combatant"])
            self.server.combatants.append(c)
            self.server.combatants.sort(key=lambda x: x.initiative, reverse=True)

        elif action == "combatant_removed":
            self.server.combatants = [
                c for c in self.server.combatants if c.name != event["name"]
            ]

        elif action in ("token_moved", "token_placed"):
            name, pos = event["name"], event["pos"]
            for c in self.server.combatants:
                if c.name == name:
                    c.pos = pos
                    break

        elif action == "turn_advanced":
            self.server.turn = event.get("turn", self.server.turn)
            active_name = event.get("active")
            if active_name:
                for i, c in enumerate(self.server.combatants):
                    if c.name == active_name:
                        self.server.active_index = i
                        break

        elif action == "door_toggled":
            x, y = event["x"], event["y"]
            tile_type = event.get("tile_type", 3)
            state = event["state"]
            key = (y, x)
            if tile_type == 4:
                self.server.iron_door_states[key] = state
            elif tile_type == 5:
                self.server.secret_door_states[key] = state
            elif tile_type == 6:
                self.server.trap_states[key] = state
            else:
                self.server.door_states[key] = state

        elif action == "player_lock_changed":
            lock_type = event.get("lock_type", "move")
            if lock_type == "select":
                self.server.player_selection_locks[event["name"]] = event["locked"]
            elif lock_type == "aoe":
                self.server.player_aoe_locks[event["name"]] = event["locked"]
            else:
                self.server.player_move_locks[event["name"]] = event["locked"]

        elif action == "aoe_added":
            aoe = event.get("aoe")
            if aoe:
                self.server.aoe_areas.append(aoe)

        elif action == "aoe_removed":
            aoe_id = event.get("id")
            self.server.aoe_areas = [a for a in self.server.aoe_areas if a["id"] != aoe_id]

        elif action == "map_visibility_changed":
            self.server.map_visible = event.get("visible", False)

        elif action == "highlights_changed":
            self.server.tile_highlights = list(event.get("highlights", []))

        elif action == "map_object_added":
            obj = event.get("object")
            if obj:
                self.server.map_objects.append(obj)

        elif action == "map_object_removed":
            pos = event.get("pos")
            self.server.map_objects = [o for o in self.server.map_objects if o["pos"] != pos]

        elif action == "light_source_added":
            ls = event.get("light")
            if ls:
                self.server.light_sources.append(ls)

        elif action == "light_source_removed":
            pos = event.get("pos")
            self.server.light_sources = [ls for ls in self.server.light_sources if ls["pos"] != pos]

        elif action == "explored_updated":
            new_tiles = {tuple(t) for t in event.get("new_tiles", [])}
            self.server.explored_tiles.setdefault(self.name, set()).update(new_tiles)

        elif action == "visibility_radius_changed":
            self.server.visibility_radius = event.get("radius", 10)

        # selection_changed, selection_cleared, map_loaded, player_connected,
        # player_disconnected, error — no mirror state change needed;
        # subscribers (MapManager / Game) handle them as needed.

    # ------------------------------------------------------------------
    # Outgoing intents (called by MapManager via submit())
    # ------------------------------------------------------------------

    def submit(self, intent: dict):
        """Forward an intent to the DM server. Thread-safe."""
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(self._send(intent), self._loop)

    async def _send(self, intent: dict):
        if self._ws:
            try:
                await self._ws.send(json.dumps(intent))
            except Exception:
                pass  # reconnect loop will re-establish the connection
