import os
import ssl
import threading
import time

from Core.server import GameServer
from Core.ws_bridge import WSBridge
from Core.map_manager import MapManager
from Core.tracker import Tracker
from Core.log_utils import log

DEFAULT_MAP_PATH  = 'Maps/sample_dungeon_matrix_with_voids.txt'
DEFAULT_SAVE_FILE = 'Data/combat_tracker_example.json'
AUTOSAVE_INTERVAL = 120   # seconds between autosaves
AUTOSAVE_SLOTS    = 4     # number of rotating autosave files


class Game:

    def __init__(self, dir_path, mode='both', verbose=False, super_verbose=False,
                 host='0.0.0.0', port=8765, player_name=None, player_color='white',
                 password=None, insecure=False, cert=None, key=None):
        self.mode = mode
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose

        self.server = None
        self.bridge = None
        self.tracker = None
        self.map_manager = None
        self.player_client = None

        # Map thread state
        self._map_thread: threading.Thread | None = None
        self._programmatic_map_close = False   # True when WE close the window, not the user
        self._quit_event = threading.Event()   # used in player mode to keep main thread alive

        if mode == 'player':
            self._init_player(host, port, player_name, player_color, insecure)
        elif mode == 'dm':
            self._init_dm(host, port, password, cert, key)
        else:
            self._init_local(mode)

    # ------------------------------------------------------------------
    # Mode initialisers
    # ------------------------------------------------------------------

    def _init_local(self, mode):
        """--mode both / map / tracker — local play."""
        self.server = GameServer()
        self.bridge = WSBridge(self.server)
        self.bridge.start()

        if self.verbose:
            log(f"[Game] WebSocket bridge on ws://{self.bridge.host}:{self.bridge.port}")

        if mode != 'map':
            self.tracker = Tracker(
                server=self.server,
                submit=self.bridge.submit,
                dir_path=self.dir_path,
                verbose=self.verbose,
                super_verbose=self.super_verbose,
            )

        map_path = DEFAULT_MAP_PATH if mode == 'map' else None
        self.map_manager = MapManager(
            server=self.server,
            dir_path=self.dir_path,
            map_path=map_path,
            submit=self.bridge.submit,
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )
        if mode == 'both':
            self.map_manager._window_title = "D&D Map Grid — DM"

        self.server.subscribe(self.map_manager.handle_server_event)
        if self.tracker:
            self.server.subscribe(self.tracker.handle_server_event)
        self.server.subscribe(self._handle_map_events)

        if self.verbose:
            log(f"[Game] Initialized in mode: {mode}")

    def _init_dm(self, host, port, password, cert, key):
        """--mode dm — full DM GUI + TLS WebSocket server for remote players."""
        from Core.cert_utils import ensure_cert

        cert_path, key_path = ensure_cert(
            cert_path=cert or "dm_cert.pem",
            key_path=key  or "dm_key.pem",
        )
        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(cert_path, key_path)

        self.server = GameServer()
        self.bridge = WSBridge(
            self.server,
            host=host or '0.0.0.0',
            port=port,
            password=password,
            ssl_context=ssl_ctx,
        )
        self.bridge.start()

        print(f"[DungeonPy] DM server listening on wss://*:{self.bridge.port}")
        print(f"[DungeonPy] Share your public IP + port with players.")
        if self.verbose:
            log(f"[Game] DM bridge on wss://{host}:{self.bridge.port}")

        self.tracker = Tracker(
            server=self.server,
            submit=self.bridge.submit,
            dir_path=self.dir_path,
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )
        self.map_manager = MapManager(
            server=self.server,
            dir_path=self.dir_path,
            map_path=None,
            submit=self.bridge.submit,
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )
        self.map_manager._window_title = "D&D Map Grid — DM"

        self.server.subscribe(self.tracker.handle_server_event)
        self.server.subscribe(self.map_manager.handle_server_event)
        self.server.subscribe(self._handle_map_events)

    def _init_player(self, host, port, player_name, player_color, insecure):
        """--mode player — remote map-only client; no local files needed."""
        from Core.player_client import PlayerClient
        from Core.player_chat_window import PlayerChatWindow

        if not player_name:
            raise ValueError("--name is required for --mode player")

        ssl_ctx = ssl.create_default_context()
        if insecure:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        self.server = GameServer()   # mirror — filled from server snapshots

        self.map_manager = MapManager(
            server=self.server,
            dir_path=self.dir_path,
            map_path=None,           # grid arrives via snapshot
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )

        self.player_client = PlayerClient(
            server=self.server,
            host=host,
            port=port,
            name=player_name,
            color=player_color,
            ssl_context=ssl_ctx,
        )
        self.map_manager._submit = self.player_client.submit
        self.map_manager._center_on_player = player_name
        self.map_manager._window_title = f"D&D Map Grid — {player_name}"

        self._player_chat = PlayerChatWindow(
            player_name=player_name,
            submit_fn=self.player_client.submit,
        )

        self.server.subscribe(self.map_manager.handle_server_event)
        self.server.subscribe(self._handle_player_map_events)
        self.server.subscribe(self._player_chat.handle_server_event)
        self.player_client.start()   # blocks until first handshake (15 s timeout)

        if self.verbose:
            log(f"[Game] Player '{player_name}' connected to {host}:{port}")

    # ------------------------------------------------------------------
    # Map window lifecycle
    # ------------------------------------------------------------------

    def _open_map(self):
        """Start the map window on a daemon thread (no-op if already open)."""
        if self._map_thread and self._map_thread.is_alive():
            return
        self.map_manager.running = True
        self._map_thread = threading.Thread(
            target=self._run_map_thread, daemon=True, name='map-window'
        )
        self._map_thread.start()

    def _close_map(self):
        """Signal the map window to close (the thread stops itself)."""
        self._programmatic_map_close = True
        self.map_manager.running = False

    def _run_map_thread(self):
        """Entry point for the map daemon thread."""
        screen = self.map_manager.init_pygame()
        self.map_manager.run_loop(screen)
        # run_loop has exited — determine why
        if not self._programmatic_map_close:
            # User closed the pygame window manually
            if self.mode == 'player':
                self._quit_event.set()   # causes chat window loop to exit too
            elif self.mode in ('dm', 'both'):
                # Treat window close as toggling the map off for everyone
                self.bridge.submit({"action": "set_map_visible", "visible": False})
        self._programmatic_map_close = False

    def _handle_map_events(self, event):
        """DM/both mode: open or close the map window in response to server events."""
        action = event.get("action")
        if action == "map_loaded":
            self._open_map()
        elif action == "map_visibility_changed":
            if event.get("visible"):
                self._open_map()
            else:
                self._close_map()

    def _handle_player_map_events(self, event):
        """Player mode: open map when placed + visible; close when toggled off."""
        player_name = self.player_client.name

        if event.get("type") == "snapshot":
            # Only act on the first snapshot after connect (initial state restore)
            if not getattr(self, '_player_first_snapshot_done', False):
                self._player_first_snapshot_done = True
                if self.server.map_visible:
                    token = next(
                        (c for c in self.server.combatants
                         if c.name == player_name and c.pos), None
                    )
                    if token:
                        self._open_map()
            return

        action = event.get("action")
        if action == "map_visibility_changed":
            if event.get("visible"):
                token = next(
                    (c for c in self.server.combatants
                     if c.name == player_name and c.pos), None
                )
                if token:
                    self._open_map()
            else:
                self._close_map()

        elif action in ("token_placed", "token_moved"):
            if event.get("name") == player_name and self.server.map_visible:
                self._open_map()

    # ------------------------------------------------------------------
    # Autosave
    # ------------------------------------------------------------------

    def _start_autosave(self):
        slot = [0]  # mutable container so the closure can mutate it

        def _loop():
            while True:
                time.sleep(AUTOSAVE_INTERVAL)
                slot[0] = (slot[0] % AUTOSAVE_SLOTS) + 1
                path = os.path.join(
                    self.dir_path, 'Data', f'autosave_{slot[0]}.json'
                )
                self.server.submit({"action": "save", "path": path})
                if self.verbose:
                    log(f"[Game] Autosaved to {path}")

        threading.Thread(target=_loop, daemon=True, name='autosave').start()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        if self.verbose:
            log(f"[Game] Launching in {self.mode} mode...")

        if self.mode == 'player':
            self._player_chat.run(self._quit_event)  # blocks until chat window closes

        elif self.mode == 'map':
            screen = self.map_manager.init_pygame()
            self.map_manager.run_loop(screen)

        elif self.mode == 'tracker':
            save_path = os.path.join(self.dir_path, DEFAULT_SAVE_FILE)
            self.server.submit({"action": "load", "path": save_path})
            self.tracker.run_gui(self.dir_path)

        elif self.mode in ('both', 'dm'):
            save_path = os.path.join(self.dir_path, DEFAULT_SAVE_FILE)
            self.server.submit({"action": "load", "path": save_path})
            self._start_autosave()
            # Tracker runs on the main thread (blocking until window closes)
            self.tracker.run_gui(self.dir_path)

        self.shutdown()

    def shutdown(self):
        if self.verbose:
            log("[Game] Shutting down.")
        if self.bridge:
            self.bridge.stop()
        if self.player_client:
            self.player_client.stop()
