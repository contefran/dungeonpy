import os
import ssl
import threading

from Core.server import GameServer
from Core.ws_bridge import WSBridge
from Core.map_manager import MapManager
from Core.tracker import Tracker
from Core.log_utils import log

DEFAULT_MAP_PATH  = 'Maps/sample_dungeon_matrix_with_voids.txt'
DEFAULT_SAVE_FILE = 'Data/combat_tracker_example.json'


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
        self.screen = None
        self.player_client = None

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
        """--mode both / map / tracker  — unchanged local behaviour."""
        self.server = GameServer()
        self.bridge = WSBridge(self.server)
        self.bridge.start()

        if self.verbose:
            log(f"[Game] WebSocket bridge on ws://{self.bridge.host}:{self.bridge.port}")

        self.tracker = Tracker(
            server=self.server,
            submit=self.bridge.submit,
            dir_path=self.dir_path,
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )

        if mode in ('map', 'both'):
            self.map_manager = MapManager(
                server=self.server,
                dir_path=self.dir_path,
                map_path=DEFAULT_MAP_PATH,
                submit=self.bridge.submit,
                verbose=self.verbose,
                super_verbose=self.super_verbose,
            )
            self.screen = self.map_manager.init_pygame()

        self.server.subscribe(self.tracker.handle_server_event)
        if self.map_manager:
            self.server.subscribe(self.map_manager.handle_server_event)

        if self.verbose:
            log(f"[Game] Initialized in mode: {mode}")

    def _init_dm(self, host, port, password, cert, key):
        """--mode dm  — full DM GUI + TLS WebSocket server for remote players."""
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
            map_path=DEFAULT_MAP_PATH,
            submit=self.bridge.submit,
            verbose=self.verbose,
            super_verbose=self.super_verbose,
        )
        self.screen = self.map_manager.init_pygame()

        self.server.subscribe(self.tracker.handle_server_event)
        self.server.subscribe(self.map_manager.handle_server_event)

    def _init_player(self, host, port, player_name, player_color, insecure):
        """--mode player  — remote map-only client; no local files needed."""
        from Core.player_client import PlayerClient

        if not player_name:
            raise ValueError("--name is required for --mode player")

        ssl_ctx = ssl.create_default_context()
        if insecure:
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        self.server = GameServer()  # mirror — filled from server snapshots

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

        self.server.subscribe(self.map_manager.handle_server_event)
        self.screen = self.map_manager.init_pygame()
        self.player_client.start()   # blocks until first handshake (15 s timeout)

        if self.verbose:
            log(f"[Game] Player '{player_name}' connected to {host}:{port}")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self):
        if self.verbose:
            log(f"[Game] Launching in {self.mode} mode...")

        if self.mode == 'player':
            self.map_manager.run_loop(self.screen)

        elif self.mode == 'map':
            self.map_manager.run_loop(self.screen)

        elif self.mode == 'tracker':
            self.tracker.run_gui(self.dir_path)

        elif self.mode in ('both', 'dm'):
            save_path = os.path.join(self.dir_path, DEFAULT_SAVE_FILE)
            # Synchronous load so the tracker sees the correct state at startup
            self.server.submit({"action": "load", "path": save_path})
            # Expose the map grid so arriving players receive it in their snapshot
            if self.map_manager:
                self.server.map_grid = self.map_manager.map_data

            tracker_thread = threading.Thread(
                target=self.tracker.run_gui,
                args=(self.dir_path,),
                daemon=True,
            )
            tracker_thread.start()
            self.map_manager.run_loop(self.screen)

        self.shutdown()

    def shutdown(self):
        if self.verbose:
            log("[Game] Shutting down.")
        if self.bridge:
            self.bridge.stop()
        if self.player_client:
            self.player_client.stop()
