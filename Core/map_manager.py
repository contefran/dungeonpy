import pygame
import os
from Core.socket_bridge import SocketBridge
import math

class MapManager:

    def __init__(self, map_path, dir_path, verbose=False, super_verbose=False):
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
        self.door_states = {}
        self.secret_door_states = {}

        self.floor_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor3.jpg')
        self.wall_texture_original = pygame.image.load(dir_path + 'Textures/stonefloor4.jpg')
        self.closed_door_texture_original = pygame.image.load(dir_path + 'Textures/closed_door1.png')
        self.open_door_texture_original = pygame.image.load(dir_path + 'Textures/open_door1.png')
        self.secret_door_texture_original = self.wall_texture_original
        self.floor_texture, self.wall_texture, self.secret_door_texture, self.closed_door_texture, self.open_door_texture = self.scale_textures(self.tile_size)

        self.combatants = []
        self.dragging_token = None
        self.drag_candidate = None
        self.dragging_offset = (0, 0)
        self.initial_token_pos = None
        self.unplaced = []
        self.bridge = None

    def init_pygame(self):
        pygame.init()
        info = pygame.display.Info()
        screen_width = int(info.current_w * 0.5)
        screen_height = int(info.current_h * 0.5)
        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)
        pygame.display.set_caption("D&D Map Grid")

        self.floor_texture_original = self.floor_texture_original.convert()
        self.wall_texture_original = self.wall_texture_original.convert()
        self.closed_door_texture_original = self.closed_door_texture_original.convert_alpha()
        self.open_door_texture_original = self.open_door_texture_original.convert_alpha()

        clock = pygame.time.Clock()
        return screen, clock

    def load_map_from_txt(self, filepath):
        with open(filepath, "r") as f:
            lines = f.readlines()
        return [[int(ch) for ch in line.strip()] for line in lines]

    def render(self, screen, selected_token, active_combatant):
        screen.fill((0, 0, 0))
        self.draw_map(screen)
        self.draw_grid(screen)
        mx, my = pygame.mouse.get_pos()
        self.draw_tokens(screen, selected_token, active_combatant, (mx, my))
        self.draw_minimap(screen)
        
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

    def load_icon(self,file):
        try:
            img = pygame.image.load(self.dir_path + "Icons/" + file).convert_alpha()
            self.icons[file] = pygame.transform.smoothscale(img, (self.tile_size, self.tile_size))
        except Exception as e:
            print(f"Could not load icon {file}: {e}")
        return self.icons.get(file)

    def is_tile_occupied(self, x, y, ignore_token=None):
        for c in self.combatants:
            if c == ignore_token:
                continue
            if c.pos == [x, y]:
                return True
        return False
    
    def toggle_door(self, x, y):
        tile = self.map_data[y][x]
        key = (y, x)
        if tile == 3:  # Normal door
            current = self.door_states.get(key, 'closed')
            new = 'closed' if current == 'open' else 'open'
            self.door_states[key] = new
            if self.verbose:
                print(f"[Map] Door at ({x},{y}) toggled to: {new}")
        elif tile == 4:  # Secret door
            current = self.secret_door_states.get(key, 'closed')
            new = 'closed' if current == 'open' else 'open'
            self.secret_door_states[key] = new
            if self.verbose:
                print(f"[Map] Secret door at ({x},{y}) toggled to: {new}")

    def get_pixel_coords(self, grid_pos):
        cx, cy = grid_pos
        return cx * self.tile_size + self.offset_x, cy * self.tile_size + self.offset_y

    def draw_map(self, screen):
        for row in range(len(self.map_data)):
            for col in range(len(self.map_data[0])):
                x = col * self.tile_size + self.offset_x
                y = row * self.tile_size + self.offset_y
                tile = self.map_data[row][col]
                key = (row, col)

                if tile == 4:
                    screen.blit(self.wall_texture, (x, y))
                    if self.secret_door_states.get(key) == "open":
                        screen.blit(self.open_door_texture, (x, y))
                elif tile == 3:
                    screen.blit(self.floor_texture, (x, y))
                    if self.door_states.get(key) == "open":
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
        for i, c in enumerate(self.combatants):
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
                #if self.verbose:
                #    print(f"[Map] Drawing {c.name} icon at ({x}, {y})")
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

            #if self.verbose:
            #    print(f"[Map] Token {c.name} position: {c.pos}, rectangle: ({x}, {y}, {self.tile_size}, {self.tile_size})")

    def draw_minimap(self, screen):
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        scale = 0.04
        mini_w = int(cols * self.tile_size * scale)
        mini_h = int(rows * self.tile_size * scale)
        mini_pos = (10, 10)

        pygame.draw.rect(screen, (30, 30, 30), (*mini_pos, mini_w, mini_h))
        mini_tile_w = mini_w / cols
        mini_tile_h = mini_h / rows

        for row in range(rows):
            for col in range(cols):
                color = (100, 60, 40) if self.map_data[row][col] == 1 else (210, 210, 200)
                rect = pygame.Rect(
                    mini_pos[0] + col * mini_tile_w,
                    mini_pos[1] + row * mini_tile_h,
                    mini_tile_w,
                    mini_tile_h
                )
                pygame.draw.rect(screen, color, rect)

        # Viewport rectangle
        screen_w, screen_h = screen.get_size()
        map_px_w = cols * self.tile_size
        map_px_h = rows * self.tile_size
        center_x = screen_w / 2 - self.offset_x
        center_y = screen_h / 2 - self.offset_y
        ratio_x = screen_w / map_px_w
        ratio_y = screen_h / map_px_h

        view_x = mini_pos[0] + (center_x / map_px_w) * mini_w - (ratio_x * mini_w) / 2
        view_y = mini_pos[1] + (center_y / map_px_h) * mini_h - (ratio_y * mini_h) / 2
        view_rect = pygame.Rect(view_x, view_y, ratio_x * mini_w, ratio_y * mini_h)
        pygame.draw.rect(screen, (255, 0, 0), view_rect, 2)

    def run_loop(self, screen, tracker, selected_token_ref, running_flag):
        clock = pygame.time.Clock()
        while running_flag[0]:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running_flag[0] = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running_flag[0] = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.handle_click(event.pos, 1, selected_token_ref, self.unplaced)
                        if selected_token_ref[0]:
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

            self.render(screen, selected_token_ref[0], tracker.get_active())
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
            print(f"[Map] Zoom level changed to tile_size = {self.tile_size}")

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
                print(f"[Map] Panning by ({dx}, {dy})")

    def handle_click(self, pos, button, selected_token_ref, unplaced_list):
        mx, my = pos
        col = (mx - self.offset_x) // self.tile_size
        row = (my - self.offset_y) // self.tile_size

        if self.verbose:
            print(f"[Map] Mouse click at pixel=({mx},{my}) tile=({col},{row})")

        if button == 1:
            if 0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data):
                tile = self.map_data[row][col]
                if tile == 3 or tile == 4:  # Only if it's a door or secret door
                    self.toggle_door(col, row)
                    if self.verbose:
                        print(f"[Map] Toggled door at ({col}, {row})")

            selected_token_ref[0] = None
            for c in self.combatants:
                if not c.pos:
                    if self.verbose:
                        print(f"[Map] Skipping token {c.name} — no position set")
                    continue
                else:
                    cx, cy = c.pos
                    x = cx * self.tile_size + self.offset_x
                    y = cy * self.tile_size + self.offset_y
                    rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                    if self.super_verbose:
                        print(f"[Map] Checking token {c.name} at tile {c.pos} -> pixel ({x},{y})")
                        print(f"rect: {rect}, tile size: {self.tile_size}, offset: ({self.offset_x}, {self.offset_y})")
                    if rect.collidepoint(mx, my):
                        selected_token_ref[0] = c
                        self.send_to_tracker(f"{c.name} selected")
                        if self.super_verbose:
                            print(f"[Map] Selected token: {c.name}")
                            print(f"[Map] Token rectangle: ({x}, {y}, {self.tile_size}, {self.tile_size})")
                        break

            if unplaced_list:
                combatant = unplaced_list.pop(0)
                combatant.pos = [col, row]
                if combatant.icon:
                    self.load_icon(combatant.icon)
                self.combatants.append(combatant)
                selected_token_ref[0] = combatant
                self.send_to_tracker(f"{combatant.name} selected")
                if self.verbose:
                    print(f"[Map] Placed new token: {combatant.name} at ({col},{row})")

    def get_token_at_pixel(self, mx, my):
        for c in self.combatants:
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
                    print(f"[Map] Dragging token: {self.dragging_token.name} from {self.dragging_token.pos}")

        if self.dragging_token:
            icon_x = mx - self.dragging_offset[0] + (self.tile_size // 2)
            icon_y = my - self.dragging_offset[1] + (self.tile_size // 2)
            self.dragging_token.pos = [
                (icon_x - self.offset_x) // self.tile_size,
                (icon_y - self.offset_y) // self.tile_size
            ]

    def drop_token(self, mx, my):
        if not self.dragging_token:
            self.drag_candidate = None  # Clear any pending drag
            return
        col = (mx - self.offset_x) // self.tile_size
        row = (my - self.offset_y) // self.tile_size

        if (0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data)
            and not self.is_tile_occupied(col, row, ignore_token=self.dragging_token)):
            self.dragging_token.pos = [col, row]
            if self.verbose:
                print(f"[Map] Dropped token {self.dragging_token.name} at ({col},{row})")
        else:
            self.dragging_token.pos = self.initial_token_pos
            if self.verbose:
                print(f"[Map] Invalid drop, reverted {self.dragging_token.name} to {self.initial_token_pos}")

        self.dragging_token = None
        self.drag_candidate = None
        self.initial_token_pos = None

    def start_socket_server(self, tracker, selected_token_ref):
        def handle_message(message):
            if self.verbose:
                print(f"[Map] Received message: {message}")

            if message == "CLEAR_SELECTION":
                selected_token_ref[0] = None
            elif message.endswith(" selected"):
                name = message.replace(" selected", "")
                for c in self.combatants:
                    if c.name == name:
                        selected_token_ref[0] = c
                        break
            elif message.endswith(" active"):
                name = message.replace(" active", "")
                for i, c in enumerate(self.combatants):
                    if c.name == name:
                        tracker.active_index = i
                        break

        self.bridge = SocketBridge(65433, on_message=handle_message, verbose=self.verbose)

    def send_to_tracker(self, message):
        if self.verbose:
            print(f"[Map] Sending to tracker: {message}")
        if self.bridge:
            self.bridge.send(65432, message)
