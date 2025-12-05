from Core.map_manager import MapManager
from Core.tracker import Tracker
import threading
from datetime import datetime

class Game:
    
    def __init__(self, dir_path, mode='map', verbose=False, super_verbose=False):
        self.mode = mode
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose
        self.running = True
        self.tracker = Tracker(verbose=self.verbose)
        self.map_manager = None
        self.screen = None
        self.clock = None

        if self.mode in ['map', 'both']:
            self.map_manager = MapManager(
                map_path='Maps/sample_dungeon_matrix_with_voids.txt',
                dir_path=dir_path,
                verbose=self.verbose
            )
            self.screen, self.clock = self.map_manager.init_pygame()
            self.map_manager.combatants = self.tracker.combatants
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Game] Initialized in mode: {self.mode}")

    def run(self):
        if self.verbose:
            print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
            print(f"[Game] Launching in {self.mode} mode...")

        if self.mode == 'map':
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print("[Game] Starting map-only loop.")

            selected_token = [None]
            running_flag = [True]
            self.map_manager.run_loop(
                screen=self.screen,
                tracker=self.tracker,
                selected_token_ref=selected_token,
                running_flag=running_flag
            )
        elif self.mode == 'tracker':
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print("[Game] Starting tracker gui only.")
            self.tracker.run_gui(self.dir_path)

        elif self.mode == 'both':
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print("[Game] Starting map and tracker.")

            file_path = self.dir_path + 'Data/combat_tracker_example.json'
            self.tracker.load_from_file(file_path)
            self.map_manager.combatants = self.tracker.combatants
            self.map_manager.unplaced = [c for c in self.tracker.combatants if c.pos is None]
            for c in self.tracker.combatants:
                if c.icon:
                    self.map_manager.load_icon(c.icon)

            selected_token = [None]
            running_flag = [True]

            self.map_manager.start_socket_server(
                tracker=self.tracker,
                selected_token_ref=selected_token
            )

            tracker_thread = threading.Thread(
                target=self.tracker.run_gui,
                args=(self.dir_path,),
                daemon=True
            )
            tracker_thread.start()

            self.map_manager.run_loop(
                screen=self.screen,
                tracker=self.tracker,
                selected_token_ref=selected_token,
                running_flag=running_flag
            )

        self.shutdown()

    def _update(self):
        pass  # For now, nothing to update outside of input/rendering

    def shutdown(self):
        print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
        print("[Game] Shutting down socket bridges...")
        if hasattr(self.tracker, "bridge") and self.tracker.bridge:
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print("[Game] Shutting down tracker bridge...")
            self.tracker.bridge.stop()

        if self.map_manager and hasattr(self.map_manager, "bridge") and self.map_manager.bridge:
            if self.verbose:
                print(f"[{datetime.now().strftime('%-I:%M:%S')}.{datetime.now().microsecond // 1000} {datetime.now().strftime('%p')}]", end='')
                print("[Game] Shutting down map manager bridge...")
            self.map_manager.bridge.stop()
        
