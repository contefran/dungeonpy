from Core.server import GameServer
from Core.ws_bridge import WSBridge
from Core.map_manager import MapManager
from Core.tracker import Tracker
from Core.log_utils import log
import os
import threading

DEFAULT_MAP_PATH     = 'Maps/sample_dungeon_matrix_with_voids.txt'
DEFAULT_SAVE_FILE    = 'Data/combat_tracker_example.json'


class Game:

    def __init__(self, dir_path, mode='map', verbose=False, super_verbose=False):
        self.mode = mode
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose

        self.server = GameServer()
        self.bridge = WSBridge(self.server)
        self.bridge.start()

        if self.verbose:
            log(f"[Game] WebSocket bridge listening on ws://{self.bridge.host}:{self.bridge.port}")

        self.tracker = Tracker(
            server=self.server,
            submit=self.bridge.submit,
            dir_path=dir_path,
            verbose=verbose,
            super_verbose=super_verbose,
        )
        self.map_manager = None
        self.screen = None

        if self.mode in ['map', 'both']:
            self.map_manager = MapManager(
                server=self.server,
                map_path=DEFAULT_MAP_PATH,
                dir_path=dir_path,
                submit=self.bridge.submit,
                verbose=verbose,
                super_verbose=super_verbose,
            )
            self.screen = self.map_manager.init_pygame()

        # Subscribe both clients to server events
        self.server.subscribe(self.tracker.handle_server_event)
        if self.map_manager:
            self.server.subscribe(self.map_manager.handle_server_event)

        if self.verbose:
            log(f"[Game] Initialized in mode: {self.mode}")

    def run(self):
        if self.verbose:
            log(f"[Game] Launching in {self.mode} mode...")

        if self.mode == 'map':
            if self.verbose:
                log("[Game] Starting map-only loop.")
            self.map_manager.run_loop(self.screen)

        elif self.mode == 'tracker':
            if self.verbose:
                log("[Game] Starting tracker GUI only.")
            self.tracker.run_gui(self.dir_path)

        elif self.mode == 'both':
            if self.verbose:
                log("[Game] Starting map and tracker.")

            # Load initial state — snapshot is broadcast to all subscribers
            self.bridge.submit({"action": "load", "path": os.path.join(self.dir_path, DEFAULT_SAVE_FILE)})

            tracker_thread = threading.Thread(
                target=self.tracker.run_gui,
                args=(self.dir_path,),
                daemon=True
            )
            tracker_thread.start()

            self.map_manager.run_loop(self.screen)

        self.shutdown()

    def shutdown(self):
        if self.verbose:
            log("[Game] Shutting down.")
        self.bridge.stop()
