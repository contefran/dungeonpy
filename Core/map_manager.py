import pygame
import os
from Core.log_utils import log
import math

class MapManager:

    def __init__(self, server, map_path, dir_path, verbose=False, super_verbose=False):
        self.server = server
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose
        self.map_data = self.load_map_from_txt(os.path.join(dir_path, map_path))

        self.tile_size = 60
        self.min_tile_size = 20
        self.max_tile_size = 120

        self.offset_x = 0
        self.offset_y = 0
        self.panning = False
        self.pan_start = (0, 0)

        self.icons = {}
        self.unplaced = []
        self.selected_token = None
        self.running = True

        self.floor_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor3.jpg')
        self.wall_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor4.jpg')
        self.closed_door_texture_original = pygame.image.load(dir_path + 'Textures/closed_door1.png')
        self.open_door_texture_original = pygame.image.load(dir_path + 'Textures/open_door1.png')
        self.secret_door_texture_original = self.wall_texture_original
        self.floor_texture, self.wall_texture, self.secret_door_texture, self.closed_door_texture, self.open_door_texture = self.scale_textures(self.tile_size)

        self.dragging_token = None
        self.drag_candidate = None
        self.dragging_offset = (0, 0)
        self.initial_token_pos = None
        self.ui_font = None
        self._minimap_surface = None

    def init_pygame(self):
        pygame.init()
        info = pygame.display.Info()
        screen_width = int(info.current_w * 0.5)
        screen_height = int(info.current_h * 0.5)

        map_pixel_width = len(self.map_data[0]) * self.tile_size
        map_pixel_height = len(self.map_data) * self.tile_size
        # Center the map
        self.offset_x = (screen_width // 2) - (map_pixel_width // 2)
        self.offset_y = (screen_height // 2) - (map_pixel_height // 2)

        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)
        pygame.display.set_caption("D&D Map Grid")

        self.floor_texture_original = self.floor_texture_original.convert()
        self.wall_texture_original = self.wall_texture_original.convert()
        self.closed_door_texture_original = self.closed_door_texture_original.convert_alpha()
        self.open_door_texture_original = self.open_door_texture_original.convert_alpha()

        self.ui_font = pygame.font.SysFont('Arial', 18)
        self._build_minimap_surface()
        clock = pygame.time.Clock()
        return screen, clock

    def load_map_from_txt(self, filepath):
        with open(filepath, "r") as f:
            lines = f.readlines()
        return [[int(ch) for ch in line.strip()] for line in lines]

    def render(self, screen):
        screen.fill((0, 0, 0))
        self.draw_map(screen)
        self.draw_grid(screen)
        mx, my = pygame.mouse.get_pos()
        self.draw_tokens(screen, self.selected_token, self.server.get_active(), (mx, my))
        self.draw_minimap(screen)
        if self.unplaced and self.ui_font:
            label = f"Click to place: {self.unplaced[0].name}"
            text = self.ui_font.render(label, True, (255, 220, 50))
            x = screen.get_width() // 2 - text.get_width() // 2
            y = screen.get_height() - text.get_height() - 10
            screen.blit(text, (x, y))

    def scale_textures(self, tile_size):
        return (
            pygame.transform.scale(self.floor_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.wall_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.secret_door_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.closed_door_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.open_door_texture_original, (tile_size, tile_size))
        )

    def rescale_icons(self):
        for file, icon in self.icons.items():
            try:
                img = pygame.image.load(self.dir_path + "Icons/" + file).convert_alpha()
                self.icons[file] = pygame.transform.smoothscale(img, (self.tile_size, self.tile_size))
            except Exception as e:
                print(f"Could not rescale icon {file}: {e}")

    def load_icon(self, file):
        try:
            img = pygame.image.load(self.dir_path + "Icons/" + file).convert_alpha()
            self.icons[file] = pygame.transform.smoothscale(img, (self.tile_size, self.tile_size))
        except Exception as e:
            print(f"Could not load icon {file}: {e}")
        return self.icons.get(file)

    def is_tile_occupied(self, x, y, ignore_token=None):
        for c in self.server.combatants:
            if c == ignore_token:
                continue
            if c.pos == [x, y]:
                return True
        return False

    # ------------------------------------------------------------------
    # Server event handling (pub/sub)
    # ------------------------------------------------------------------

    def handle_server_event(self, event: dict):
        """Handle a server event — called on whatever thread submitted the triggering intent."""
        if event.get("type") == "snapshot":
            self._sync_from_snapshot(event["state"])
            return

        action = event.get("action")

        if action == "selection_changed":
            name = event["name"]
            self.selected_token = next(
                (c for c in self.server.combatants if c.name == name), None
            )

        elif action == "selection_cleared":
            self.selected_token = None

        elif action == "turn_advanced":
            # Advancing turn naturally deselects the map token
            self.selected_token = None

        elif action == "combatant_added":
            c_dict = event.get("combatant", {})
            name = c_dict.get("name")
            c = next((x for x in self.server.combatants if x.name == name), None)
            if c:
                if c.pos is None:
                    self.unplaced.append(c)
                if c.icon and c.icon not in self.icons:
                    self.load_icon(c.icon)

        elif action == "token_placed":
            name = event["name"]
            self.unplaced = [c for c in self.unplaced if c.name != name]

    def _sync_from_snapshot(self, state):
        """Rebuild local view state from a server snapshot (e.g. after load)."""
        self.unplaced = [c for c in self.server.combatants if c.pos is None]
        for c in self.server.combatants:
            if c.icon and c.icon not in self.icons:
                self.load_icon(c.icon)
        self.selected_token = None

    # ------------------------------------------------------------------
    # Map rendering
    # ------------------------------------------------------------------

    def draw_map(self, screen):
        for row in range(len(self.map_data)):
            for col in range(len(self.map_data[0])):
                x = col * self.tile_size + self.offset_x
                y = row * self.tile_size + self.offset_y
                tile = self.map_data[row][col]
                key = (row, col)

                if tile == 4:
                    screen.blit(self.wall_texture, (x, y))
                    if self.server.secret_door_states.get(key) == "open":
                        screen.blit(self.open_door_texture, (x, y))
                elif tile == 3:
                    screen.blit(self.floor_texture, (x, y))
                    if self.server.door_states.get(key) == "open":
                        screen.blit(self.open_door_texture, (x, y))
                    else:
                        screen.blit(self.closed_door_texture, (x, y))
                elif tile == 2:
                    pygame.draw.rect(screen, (0, 0, 0), (x, y, self.tile_size, self.tile_size))
                elif tile == 1:
                    screen.blit(self.wall_texture, (x, y))
                else:
                    screen.blit(self.floor_texture, (x, y))

    def draw_grid(self, screen):
        grid_color = (180, 180, 180)
        rows = len(self.map_data)
        cols = len(self.map_data[0])

        for col in range(cols + 1):
            x = col * self.tile_size + self.offset_x
            pygame.draw.line(screen, grid_color, (x, self.offset_y), (x, rows * self.tile_size + self.offset_y))

        for row in range(rows + 1):
            y = row * self.tile_size + self.offset_y
            pygame.draw.line(screen, grid_color, (self.offset_x, y), (cols * self.tile_size + self.offset_x, y))

    def draw_tokens(self, screen, selected_token=None, active_combatant=None, mouse_pos=None):
        for i, c in enumerate(self.server.combatants):
            if not c.pos:
                continue

            x, y = self.get_pixel_coords(c.pos)

            # Handle dragging tokens
            if c == self.dragging_token and mouse_pos:
                mx, my = mouse_pos
                x = mx - self.dragging_offset[0]
                y = my - self.dragging_offset[1]

            icon_file = c.icon
            if icon_file and icon_file in self.icons:
                screen.blit(self.icons[icon_file], (x, y))
            else:
                pygame.draw.circle(screen, (255, 0, 0), (x + self.tile_size // 2, y + self.tile_size // 2), self.tile_size // 3)

            # Highlight selected
            if c == selected_token:
                pygame.draw.rect(screen, (255, 255, 0), pygame.Rect(x, y, self.tile_size, self.tile_size), 3)

            # Highlight active
            if active_combatant and c == active_combatant:
                glow_radius = self.tile_size // 4 + int((self.tile_size//8) * (1 + math.sin(pygame.time.get_ticks() * 0.005)))
                glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, (135, 206, 250, 100), (glow_radius, glow_radius), glow_radius)
                screen.blit(glow_surface, (x + self.tile_size // 2 - glow_radius, y + self.tile_size // 2 - glow_radius))

    # ------------------------------------------------------------------
    # Minimap
    # ------------------------------------------------------------------

    def _build_minimap_surface(self):
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        # Fixed 2.4 px per tile (= 60 * 0.04) — independent of zoom level
        mini_w = max(1, int(cols * 2.4))
        mini_h = max(1, int(rows * 2.4))

        # Draw one pixel per tile, then scale up — avoids float-rounding grid artefacts
        pixel_surf = pygame.Surface((cols, rows))
        for row in range(rows):
            for col in range(cols):
                color = (100, 60, 40) if self.map_data[row][col] == 1 else (210, 210, 200)
                pixel_surf.set_at((col, row), color)
        self._minimap_surface = pygame.transform.scale(pixel_surf, (mini_w, mini_h))

    def _minimap_rect(self):
        """Bounding rect of the minimap on screen. Single source of truth for its position."""
        if self._minimap_surface is None:
            return None
        return pygame.Rect(10, 10, self._minimap_surface.get_width(), self._minimap_surface.get_height())

    def _recenter_on_minimap_click(self, mx, my):
        rect = self._minimap_rect()
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        map_px_w = cols * self.tile_size
        map_px_h = rows * self.tile_size
        frac_x = (mx - rect.x) / rect.width
        frac_y = (my - rect.y) / rect.height
        screen_w, screen_h = pygame.display.get_surface().get_size()
        self.offset_x = screen_w // 2 - int(frac_x * map_px_w)
        self.offset_y = screen_h // 2 - int(frac_y * map_px_h)
        if self.verbose:
            log(f"[Map] Minimap click at ({mx},{my}) -> recentered to frac ({frac_x:.2f},{frac_y:.2f})")

    def draw_minimap(self, screen):
        rect = self._minimap_rect()
        if rect is None:
            return
        screen.blit(self._minimap_surface, rect.topleft)

        # Viewport rectangle
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        screen_w, screen_h = screen.get_size()
        map_px_w = cols * self.tile_size
        map_px_h = rows * self.tile_size
        center_x = screen_w / 2 - self.offset_x
        center_y = screen_h / 2 - self.offset_y
        ratio_x = screen_w / map_px_w
        ratio_y = screen_h / map_px_h

        view_x = rect.x + (center_x / map_px_w) * rect.width  - (ratio_x * rect.width)  / 2
        view_y = rect.y + (center_y / map_px_h) * rect.height - (ratio_y * rect.height) / 2
        view_rect = pygame.Rect(view_x, view_y, ratio_x * rect.width, ratio_y * rect.height)
        pygame.draw.rect(screen, (255, 0, 0), view_rect, 2)

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def run_loop(self, screen):
        clock = pygame.time.Clock()
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.handle_click(event.pos, 1)
                        if self.selected_token:
                            self.start_drag(*event.pos)
                    elif event.button == 3:
                        self.start_panning(event.pos)

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        self.drop_token(*event.pos)
                    elif event.button == 3:
                        self.stop_panning()

                elif event.type == pygame.MOUSEMOTION:
                    self.update_panning(event.pos)
                    self.drag_token(*event.pos)

                elif event.type == pygame.MOUSEWHEEL:
                    self.handle_zoom(event)

            self.render(screen)
            pygame.display.flip()
            clock.tick(60)

        pygame.quit()

    def handle_zoom(self, event):
        prev_size = self.tile_size
        if event.y > 0:
            self.tile_size = min(self.max_tile_size, self.tile_size + 5)
        elif event.y < 0:
            self.tile_size = max(self.min_tile_size, self.tile_size - 5)

        if self.tile_size != prev_size:
            center_x, center_y = pygame.display.get_surface().get_size()
            center_x //= 2
            center_y //= 2
            self.offset_x = center_x - ((center_x - self.offset_x) * self.tile_size) // prev_size
            self.offset_y = center_y - ((center_y - self.offset_y) * self.tile_size) // prev_size
            self.floor_texture, self.wall_texture, self.secret_door_texture, self.closed_door_texture, self.open_door_texture = self.scale_textures(self.tile_size)
            self.rescale_icons()
        if self.verbose:
            log(f"[Map] Zoom level changed to tile_size = {self.tile_size}")

    def start_panning(self, pos):
        self.panning = True
        self.pan_start = pos

    def stop_panning(self):
        self.panning = False

    def update_panning(self, pos):
        if self.panning:
            dx = pos[0] - self.pan_start[0]
            dy = pos[1] - self.pan_start[1]
            self.offset_x += dx
            self.offset_y += dy
            self.pan_start = pos
            if self.verbose:
                log(f"[Map] Panning by ({dx}, {dy})")

    def handle_click(self, pos, button):
        mx, my = pos

        if button == 1:
            minimap = self._minimap_rect()
            if minimap and minimap.collidepoint(mx, my):
                self._recenter_on_minimap_click(mx, my)
                return

        col = (mx - self.offset_x) // self.tile_size
        row = (my - self.offset_y) // self.tile_size

        if self.verbose:
            log(f"[Map] Mouse click at pixel=({mx},{my}) tile=({col},{row})")

        if button == 1:
            if 0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data):
                tile = self.map_data[row][col]
                if tile == 3 or tile == 4:
                    self.server.submit({"action": "toggle_door", "x": col, "y": row, "tile_type": tile})
                    if self.verbose:
                        log(f"[Map] Toggled door at ({col}, {row})")
                    return

            hit = False
            for c in self.server.combatants:
                if not c.pos:
                    if self.verbose:
                        log(f"[Map] Skipping token {c.name} — no position set")
                    continue

                cx, cy = c.pos
                x = cx * self.tile_size + self.offset_x
                y = cy * self.tile_size + self.offset_y
                rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                if self.super_verbose:
                    log(f"[Map] Checking token {c.name} at tile {c.pos} -> pixel ({x},{y})")
                    log(f"rect: {rect}, tile size: {self.tile_size}, offset: ({self.offset_x}, {self.offset_y})")
                if rect.collidepoint(mx, my):
                    self.server.submit({"action": "select", "name": c.name})
                    if self.verbose:
                        log(f"[Map] Selected token: {c.name}")
                    hit = True
                    break

            if not hit and self.unplaced:
                combatant = self.unplaced[0]  # peek; handle_server_event removes it on token_placed
                self.server.submit({"action": "place_token", "name": combatant.name, "pos": [col, row]})
                self.server.submit({"action": "select", "name": combatant.name})
                if self.verbose:
                    log(f"[Map] Placed new token: {combatant.name} at ({col},{row})")
                hit = True

            if not hit:
                if self.verbose:
                    log(f"[Map] No token selected")
                self.server.submit({"action": "clear_selection"})

    def get_token_at_pixel(self, mx, my):
        for c in self.server.combatants:
            if c.pos:
                cx, cy = c.pos
                x = cx * self.tile_size + self.offset_x
                y = cy * self.tile_size + self.offset_y
                rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                if rect.collidepoint(mx, my):
                    return c
        return None

    def start_drag(self, mx, my):
        token = self.get_token_at_pixel(mx, my)
        if token:
            cx, cy = token.pos
            icon_x = cx * self.tile_size + self.offset_x
            icon_y = cy * self.tile_size + self.offset_y
            self.dragging_offset = (mx - icon_x, my - icon_y)
            self.initial_token_pos = token.pos[:]
            self.drag_candidate = token  # Wait for movement before confirming drag
            return token
        return None

    def drag_token(self, mx, my):
        if not self.dragging_token and self.drag_candidate:
            # Confirm drag only if mouse has moved meaningfully
            threshold = 4  # pixels
            cx, cy = self.drag_candidate.pos
            icon_x = cx * self.tile_size + self.offset_x
            icon_y = cy * self.tile_size + self.offset_y
            dx = abs(mx - icon_x)
            dy = abs(my - icon_y)
            if dx > threshold or dy > threshold:
                self.dragging_token = self.drag_candidate
                self.drag_candidate = None
                if self.verbose:
                    log(f"[Map] Dragging token: {self.dragging_token.name} from {self.dragging_token.pos}")

    def drop_token(self, mx, my):
        if not self.dragging_token:
            self.drag_candidate = None  # Clear any pending drag
            return
        col = (mx - self.offset_x) // self.tile_size
        row = (my - self.offset_y) // self.tile_size

        if (0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data)
                and not self.is_tile_occupied(col, row, ignore_token=self.dragging_token)):
            self.server.submit({"action": "move_token", "name": self.dragging_token.name, "pos": [col, row]})
            if self.verbose:
                log(f"[Map] Dropped token {self.dragging_token.name} at ({col},{row})")
        else:
            self.server.submit({"action": "move_token", "name": self.dragging_token.name, "pos": self.initial_token_pos})
            if self.verbose:
                log(f"[Map] Invalid drop, reverted {self.dragging_token.name} to {self.initial_token_pos}")

        self.dragging_token = None
        self.drag_candidate = None
        self.initial_token_pos = None

    def get_pixel_coords(self, grid_pos):
        cx, cy = grid_pos
        return cx * self.tile_size + self.offset_x, cy * self.tile_size + self.offset_y
