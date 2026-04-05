import pygame
import os
from Core.log_utils import log
from Core.los import compute_los
import math

PLAYER_COLORS = {
    "red":    (220,  50,  50),
    "blue":   ( 50, 100, 220),
    "green":  ( 50, 200,  50),
    "purple": (150,  50, 200),
    "cyan":   ( 30, 200, 220),
    "pink":   (220,  80, 180),
    "white":  (230, 230, 230),
}

# Gold is reserved for the DM (active-turn glow, selection, highlights).
# It is intentionally absent from PLAYER_COLORS so players cannot claim it.
DM_COLOR      = (255, 200, 0)
DM_COLOR_NAME = "gold"

# Combined lookup used by rendering code (highlights, remote selections).
_ALL_COLORS = {**PLAYER_COLORS, DM_COLOR_NAME: DM_COLOR}

TOOLBAR_WIDTH = 60   # pixel width of the right-side tool panel

class MapManager:

    def __init__(self, server, dir_path, submit=None,
                 map_path=None, map_data=None, verbose=False, super_verbose=False):
        self.server = server
        self._submit = submit if submit is not None else server.submit
        self.dir_path = dir_path
        self.verbose = verbose
        self.super_verbose = super_verbose
        if map_data is not None:
            self.map_data = map_data
        elif map_path is not None:
            self.map_data = self.load_map_from_txt(os.path.join(dir_path, map_path))
        else:
            self.map_data = []  # will be populated from the first snapshot

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
        self._remote_selections: dict = {}  # selector_name → (token_name, color_name)
        self._center_on_player: str | None = None  # set by Game for player mode
        self._window_title = "D&D Map Grid"
        self.running = True

        # Textures are loaded/converted in _load_textures(), called from init_pygame().
        self.floor_texture_original = None
        self.wall_texture_original = None
        self.wooden_door_closed_texture_original = None
        self.wooden_door_open_texture_original = None
        self.iron_door_closed_texture_original = None
        self.iron_door_open_texture_original = None
        self.secret_door_texture_original = None
        self.trap_texture_original = None
        self.floor_texture = None
        self.wall_texture = None
        self.wooden_door_closed_texture = None
        self.wooden_door_open_texture = None
        self.iron_door_closed_texture = None
        self.iron_door_open_texture = None
        self.secret_door_texture = None
        self.trap_texture = None

        self.dragging_token = None
        self.drag_candidate = None
        self.dragging_offset = (0, 0)
        self.initial_token_pos = None
        self.ui_font = None
        self._minimap_surface = None
        self.active_tool: str = "select"          # "select" | "highlight" | "recenter_pick" | "reveal"
        self._player_name: str | None = None      # set by Game in player mode; None = DM
        self._chat_toggle_fn = None               # set by Game in player mode; None = DM
        self._chat_visible: bool = True           # tracks chat window state for toolbar icon
        self._toolbar_font = None
        # Fog of war — player mode only
        self._explored_tiles: set = set()         # (col, row) tiles this player has ever seen
        self._current_los: set = set()            # (col, row) tiles visible this frame
        self._fog_surface: pygame.Surface | None = None  # cached per-frame fog overlay
        # Last-seen door states (fog-gated): only updated when tile is in LOS
        self._player_door_states: dict = {}       # (row, col) → state
        self._player_iron_door_states: dict = {}  # (row, col) → state

    def init_pygame(self):
        pygame.init()
        info = pygame.display.Info()
        screen_width = int(info.current_w * 0.5)
        screen_height = int(info.current_h * 0.5)

        if self.map_data:
            map_pixel_width = len(self.map_data[0]) * self.tile_size
            map_pixel_height = len(self.map_data) * self.tile_size
            self.offset_x = (screen_width // 2) - (map_pixel_width // 2)
            self.offset_y = (screen_height // 2) - (map_pixel_height // 2)
        else:
            self.offset_x = 0
            self.offset_y = 0

        screen = pygame.display.set_mode((screen_width, screen_height), pygame.RESIZABLE)
        pygame.display.set_caption(self._window_title)

        self._load_textures()

        self.ui_font = pygame.font.SysFont('Arial', 18)
        self._toolbar_font = pygame.font.SysFont('Arial', 11)
        # Re-cache icons (needed if map is reopened after close)
        self.icons = {}
        for c in self.server.combatants:
            if c.icon and c.icon not in self.icons:
                self.load_icon(c.icon)
        self._build_minimap_surface()
        if self._center_on_player:
            self._init_player_view(self._center_on_player)
            self._center_on_player = None  # disarm after first use
        return screen

    def _load_textures(self):
        """Load textures from disk and convert them. Requires an active pygame display."""
        d = self.dir_path
        self.floor_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/stonefloor3.jpg')).convert()
        self.wall_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/stonefloor4.jpg')).convert()
        self.wooden_door_closed_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/Wooden_door_closed.png')).convert_alpha()
        self.wooden_door_open_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/Wooden_door_open.png')).convert_alpha()
        self.iron_door_closed_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/Iron_door_closed.png')).convert_alpha()
        self.iron_door_open_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/Iron_door_open.png')).convert_alpha()
        self.secret_door_texture_original = self.wall_texture_original
        self.trap_texture_original = pygame.image.load(os.path.join(d, 'Assets/Textures/trap_pit.jpg')).convert_alpha()
        (self.floor_texture, self.wall_texture, self.wooden_door_closed_texture,
         self.wooden_door_open_texture, self.iron_door_closed_texture,
         self.iron_door_open_texture, self.secret_door_texture,
         self.trap_texture) = self.scale_textures(self.tile_size)

    def load_map_from_txt(self, filepath):
        def _parse(ch):
            if ch.isdigit():
                return int(ch)
            if ch.isalpha():
                return ord(ch.lower()) - ord('a') + 10
            return 0
        with open(filepath, "r") as f:
            lines = f.readlines()
        return [[_parse(ch) for ch in line.strip()] for line in lines if line.strip()]

    def render(self, screen):
        screen.fill((0, 0, 0))
        self.draw_map(screen)
        if self._player_name:
            self._update_los()
            self._draw_fog(screen)
        self.draw_grid(screen)
        self._draw_highlights(screen)
        mx, my = pygame.mouse.get_pos()
        self.draw_tokens(screen, self.selected_token, self.server.get_active(), (mx, my))
        self.draw_minimap(screen)
        if self.unplaced and self.ui_font:
            label = f"Click to place: {self.unplaced[0].name}"
            text = self.ui_font.render(label, True, (255, 220, 50))
            map_w = screen.get_width() - TOOLBAR_WIDTH
            x = map_w // 2 - text.get_width() // 2
            y = screen.get_height() - text.get_height() - 10
            screen.blit(text, (x, y))
        self._draw_toolbar(screen)

    def scale_textures(self, tile_size):
        return (
            pygame.transform.scale(self.floor_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.wall_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.wooden_door_closed_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.wooden_door_open_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.iron_door_closed_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.iron_door_open_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.secret_door_texture_original, (tile_size, tile_size)),
            pygame.transform.scale(self.trap_texture_original, (tile_size, tile_size)),
        )

    def rescale_icons(self):
        for file, icon in self.icons.items():
            try:
                img = pygame.image.load(self.dir_path + "Assets/Icons/" + file).convert_alpha()
                self.icons[file] = pygame.transform.smoothscale(img, (self.tile_size, self.tile_size))
            except Exception as e:
                print(f"Could not rescale icon {file}: {e}")

    def load_icon(self, file):
        try:
            img = pygame.image.load(self.dir_path + "Assets/Icons/" + file).convert_alpha()
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
            selector = event.get("selector")
            if selector:
                self._remote_selections[selector] = (name, event.get("color", "white"))
            else:
                self.selected_token = next(
                    (c for c in self.server.combatants if c.name == name), None
                )

        elif action == "selection_cleared":
            selector = event.get("selector")
            if selector:
                self._remote_selections.pop(selector, None)
            else:
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

        elif action == "player_lock_changed":
            # If select lock removed while highlight tool is active, revert to select
            if (event.get("lock_type") == "select" and not event.get("locked")
                    and self.active_tool == "highlight"):
                self.active_tool = "select"

        elif action == "recenter_all":
            pos = event.get("pos")
            if pos and self.map_data:
                col, row = pos
                screen = pygame.display.get_surface()
                if screen:
                    sw, sh = screen.get_size()
                    self.offset_x = sw // 2 - col * self.tile_size - self.tile_size // 2
                    self.offset_y = sh // 2 - row * self.tile_size - self.tile_size // 2

        elif action == "explored_updated":
            # Only relevant in player mode; accumulate into local explored set
            new_tiles = {tuple(t) for t in event.get("new_tiles", [])}
            self._explored_tiles.update(new_tiles)

        elif action == "map_loaded":
            # Map coords are now meaningless for old fog state — full reset
            if self._player_name:
                self._explored_tiles = set()
                self._player_door_states = {}
                self._player_iron_door_states = {}

        elif action == "secret_door_revealed":
            # Refresh map_data from server so the tile now renders as a door
            if self.server.map_grid:
                self.map_data = self.server.map_grid

        elif action == "visibility_radius_changed":
            pass  # server.visibility_radius already updated by player_client; LOS recomputed next frame

    def _init_player_view(self, player_name: str):
        """Set mid-zoom and center the view on the player's token (called once on first snapshot).
        For a no-zoom recenter use _recenter_on_player() instead."""
        mid_zoom = (self.min_tile_size + self.max_tile_size) // 2
        self.tile_size = mid_zoom
        (self.floor_texture, self.wall_texture, self.wooden_door_closed_texture,
         self.wooden_door_open_texture, self.iron_door_closed_texture,
         self.iron_door_open_texture, self.secret_door_texture,
         self.trap_texture) = self.scale_textures(self.tile_size)
        self.rescale_icons()

        token = next((c for c in self.server.combatants if c.name == player_name and c.pos), None)
        screen_w, screen_h = pygame.display.get_surface().get_size()
        if token:
            col, row = token.pos
        else:
            # Fall back to map centre if token isn't placed yet
            col = len(self.map_data[0]) // 2
            row = len(self.map_data) // 2
        self.offset_x = screen_w // 2 - col * self.tile_size - self.tile_size // 2
        self.offset_y = screen_h // 2 - row * self.tile_size - self.tile_size // 2

    def _recenter_on_player(self):
        """Re-center the view on the player's token without changing zoom."""
        if not self._player_name or not self.map_data:
            return
        token = next((c for c in self.server.combatants
                      if c.name == self._player_name and c.pos), None)
        if not token:
            return
        col, row = token.pos
        screen_w, screen_h = pygame.display.get_surface().get_size()
        self.offset_x = screen_w // 2 - col * self.tile_size - self.tile_size // 2
        self.offset_y = screen_h // 2 - row * self.tile_size - self.tile_size // 2

    def _sync_from_snapshot(self, state):
        """Rebuild local view state from a server snapshot (e.g. after load or initial connect)."""
        if state.get("map_grid"):
            self.map_data = state["map_grid"]
            import pygame as _pg
            if _pg.get_init():
                self._build_minimap_surface()
        self.unplaced = [c for c in self.server.combatants if c.pos is None]
        import pygame as _pg
        if _pg.get_init():
            for c in self.server.combatants:
                if c.icon and c.icon not in self.icons:
                    self.load_icon(c.icon)
        self.selected_token = None
        self._remote_selections.clear()
        # Restore fog state for player mode — union so periodic snapshots never shrink memory
        if self._player_name:
            player_explored = self.server.explored_tiles.get(self._player_name, set())
            self._explored_tiles |= set(player_explored)

    # ------------------------------------------------------------------
    # Toolbar helpers
    # ------------------------------------------------------------------

    def _can_highlight(self) -> bool:
        """DM can always highlight; players only when their select lock is on."""
        if self._player_name is None:
            return True
        return bool(self.server.player_selection_locks.get(self._player_name))

    def _toolbar_button_rects(self, screen_w: int) -> dict:
        """Compute toolbar button rects from current screen width."""
        x0 = screen_w - TOOLBAR_WIDTH + 8
        rects = {
            "select":    pygame.Rect(x0, 12, 44, 44),
            "highlight": pygame.Rect(x0, 64, 44, 44),
            "clear":     pygame.Rect(x0, 116, 44, 36),
        }
        if self._chat_toggle_fn is not None:
            rects["chat"] = pygame.Rect(x0, 168, 44, 44)
        if self._player_name is not None:
            chat_bottom = rects["chat"].bottom if "chat" in rects else rects["clear"].bottom
            rects["recenter"] = pygame.Rect(x0, chat_bottom + 8, 44, 44)
        if self._player_name is None:
            rects["recenter_all"] = pygame.Rect(x0, rects["clear"].bottom + 16, 44, 44)
            rects["reveal"] = pygame.Rect(x0, rects["recenter_all"].bottom + 8, 44, 44)
        return rects

    def _handle_toolbar_click(self, mx, my):
        screen_w = pygame.display.get_surface().get_width()
        rects = self._toolbar_button_rects(screen_w)
        if rects["select"].collidepoint(mx, my):
            self.active_tool = "select"
        elif rects["highlight"].collidepoint(mx, my):
            if self._can_highlight():
                self.active_tool = "highlight"
        elif rects["clear"].collidepoint(mx, my):
            if self._player_name:
                self._submit({"action": "clear_highlights"})   # bridge injects owner/color
            else:
                self._submit({"action": "clear_highlights", "owner": "DM", "color": "gold"})
        elif rects.get("chat") and rects["chat"].collidepoint(mx, my):
            if self._chat_toggle_fn:
                self._chat_toggle_fn()
                self._chat_visible = not self._chat_visible
        elif rects.get("recenter") and rects["recenter"].collidepoint(mx, my):
            self._recenter_on_player()
        elif rects.get("recenter_all") and rects["recenter_all"].collidepoint(mx, my):
            self.active_tool = "recenter_pick"
        elif rects.get("reveal") and rects["reveal"].collidepoint(mx, my):
            self.active_tool = "reveal"

    def _draw_toolbar(self, screen):
        sw, sh = screen.get_size()
        x0 = sw - TOOLBAR_WIDTH

        # Background strip + left divider
        pygame.draw.rect(screen, (25, 25, 35), (x0, 0, TOOLBAR_WIDTH, sh))
        pygame.draw.line(screen, (70, 70, 90), (x0, 0), (x0, sh), 1)

        rects = self._toolbar_button_rects(sw)
        can_hl = self._can_highlight()
        is_sel = self.active_tool == "select"
        is_hl  = self.active_tool == "highlight"

        _BG_ACTIVE   = (55, 85, 55)
        _BG_INACTIVE = (45, 45, 60)
        _BG_DISABLED = (35, 35, 42)
        _BG_CLEAR    = (80, 42, 42)
        _BORDER      = (90, 90, 110)
        _ICON        = (220, 220, 230)
        _ICON_ACTIVE = (200, 240, 200)
        _ICON_DIM    = (90,  90, 105)

        # --- Select button ---
        bg = _BG_ACTIVE if is_sel else _BG_INACTIVE
        pygame.draw.rect(screen, bg, rects["select"], border_radius=4)
        pygame.draw.rect(screen, _BORDER, rects["select"], 1, border_radius=4)
        cx, cy = rects["select"].centerx, rects["select"].centery - 6
        ic = _ICON_ACTIVE if is_sel else _ICON
        # Cursor: filled triangle (arrow-like)
        pts = [(cx - 7, cy - 8), (cx - 7, cy + 7), (cx - 1, cy + 3),
               (cx + 1, cy + 8), (cx + 4, cy + 6), (cx + 2, cy + 1), (cx + 7, cy + 1)]
        pygame.draw.polygon(screen, ic, pts)

        # --- Highlight button ---
        bg = _BG_ACTIVE if is_hl else (_BG_INACTIVE if can_hl else _BG_DISABLED)
        pygame.draw.rect(screen, bg, rects["highlight"], border_radius=4)
        pygame.draw.rect(screen, _BORDER, rects["highlight"], 1, border_radius=4)
        cx, cy = rects["highlight"].centerx, rects["highlight"].centery - 6
        ic = _ICON_ACTIVE if is_hl else (_ICON if can_hl else _ICON_DIM)
        # Star: 5-pointed
        r_out, r_in = 10, 4
        star_pts = []
        for i in range(10):
            angle = -math.pi / 2 + i * math.pi / 5
            r = r_out if i % 2 == 0 else r_in
            star_pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
        pygame.draw.polygon(screen, ic, star_pts)

        # --- Separator ---
        pygame.draw.line(screen, (55, 55, 70), (x0 + 8, 110), (sw - 8, 110), 1)

        # --- Clear button ---
        pygame.draw.rect(screen, _BG_CLEAR, rects["clear"], border_radius=4)
        pygame.draw.rect(screen, _BORDER, rects["clear"], 1, border_radius=4)
        cx, cy = rects["clear"].centerx, rects["clear"].centery
        pygame.draw.line(screen, _ICON, (cx - 7, cy - 7), (cx + 7, cy + 7), 2)
        pygame.draw.line(screen, _ICON, (cx + 7, cy - 7), (cx - 7, cy + 7), 2)

        # --- Chat button (player mode only) ---
        if self._chat_toggle_fn is not None:
            pygame.draw.line(screen, (55, 55, 70), (x0 + 8, 162), (sw - 8, 162), 1)
            is_chat = self._chat_visible
            bg = _BG_ACTIVE if is_chat else _BG_INACTIVE
            pygame.draw.rect(screen, bg, rects["chat"], border_radius=4)
            pygame.draw.rect(screen, _BORDER, rects["chat"], 1, border_radius=4)
            cx, cy = rects["chat"].centerx, rects["chat"].centery - 6
            ic = _ICON_ACTIVE if is_chat else _ICON
            # Chat bubble icon: rounded rect + small tail triangle
            bubble = pygame.Rect(cx - 10, cy - 8, 20, 14)
            pygame.draw.rect(screen, ic, bubble, 2, border_radius=3)
            tail = [(cx - 4, cy + 6), (cx - 9, cy + 11), (cx + 1, cy + 6)]
            pygame.draw.polygon(screen, ic, tail)

        # --- Recenter-all button (DM only) ---
        if rects.get("recenter_all"):
            pygame.draw.line(screen, (55, 55, 70),
                             (x0 + 8, rects["recenter_all"].top - 8),
                             (sw - 8, rects["recenter_all"].top - 8), 1)
            is_picking = self.active_tool == "recenter_pick"
            bg = (70, 55, 85) if is_picking else _BG_INACTIVE
            pygame.draw.rect(screen, bg, rects["recenter_all"], border_radius=4)
            pygame.draw.rect(screen, _BORDER, rects["recenter_all"], 1, border_radius=4)
            cx, cy = rects["recenter_all"].centerx, rects["recenter_all"].centery - 6
            ic = (200, 170, 240) if is_picking else _ICON
            # Eye icon: outer almond shape + pupil
            pygame.draw.ellipse(screen, ic, (cx - 10, cy - 5, 20, 10), 2)
            pygame.draw.circle(screen, ic, (cx, cy), 3)

        # --- Reveal button (DM only) ---
        if rects.get("reveal"):
            pygame.draw.line(screen, (55, 55, 70),
                             (x0 + 8, rects["reveal"].top - 4),
                             (sw - 8, rects["reveal"].top - 4), 1)
            is_reveal = self.active_tool == "reveal"
            bg = (70, 60, 30) if is_reveal else _BG_INACTIVE
            pygame.draw.rect(screen, bg, rects["reveal"], border_radius=4)
            pygame.draw.rect(screen, _BORDER, rects["reveal"], 1, border_radius=4)
            cx, cy = rects["reveal"].centerx, rects["reveal"].centery - 6
            ic = (240, 210, 100) if is_reveal else _ICON
            # Key icon: circle head + rectanglar shaft
            pygame.draw.circle(screen, ic, (cx - 3, cy - 4), 5, 2)
            pygame.draw.line(screen, ic, (cx + 2, cy - 2), (cx + 9, cy + 5), 2)
            pygame.draw.line(screen, ic, (cx + 6, cy + 2), (cx + 8, cy + 4), 2)

        # --- Recenter button (player mode only) ---
        if rects.get("recenter"):
            pygame.draw.line(screen, (55, 55, 70),
                             (x0 + 8, rects["recenter"].top - 4),
                             (sw - 8, rects["recenter"].top - 4), 1)
            pygame.draw.rect(screen, _BG_INACTIVE, rects["recenter"], border_radius=4)
            pygame.draw.rect(screen, _BORDER, rects["recenter"], 1, border_radius=4)
            cx, cy = rects["recenter"].centerx, rects["recenter"].centery - 6
            # Crosshair icon
            pygame.draw.circle(screen, _ICON, (cx, cy), 7, 2)
            pygame.draw.line(screen, _ICON, (cx - 11, cy), (cx - 8, cy), 2)
            pygame.draw.line(screen, _ICON, (cx + 8,  cy), (cx + 11, cy), 2)
            pygame.draw.line(screen, _ICON, (cx, cy - 11), (cx, cy - 8), 2)
            pygame.draw.line(screen, _ICON, (cx, cy + 8),  (cx, cy + 11), 2)

        # Labels beneath icons
        if self._toolbar_font:
            for key, label, active in [
                ("select",    "SEL", is_sel),
                ("highlight", "HL",  is_hl),
            ]:
                r = rects[key]
                ic = _ICON_ACTIVE if active else (_ICON if (key != "highlight" or can_hl) else _ICON_DIM)
                surf = self._toolbar_font.render(label, True, ic)
                screen.blit(surf, (r.x + (r.width - surf.get_width()) // 2, r.bottom - 13))
            clr_surf = self._toolbar_font.render("CLR", True, _ICON)
            r = rects["clear"]
            screen.blit(clr_surf, (r.x + (r.width - clr_surf.get_width()) // 2,
                                   r.y + (r.height - clr_surf.get_height()) // 2))
            if self._chat_toggle_fn is not None:
                ic = _ICON_ACTIVE if self._chat_visible else _ICON
                chat_surf = self._toolbar_font.render("CHAT", True, ic)
                r = rects["chat"]
                screen.blit(chat_surf, (r.x + (r.width - chat_surf.get_width()) // 2, r.bottom - 13))
            if rects.get("recenter"):
                ctr_surf = self._toolbar_font.render("CTR", True, _ICON)
                r = rects["recenter"]
                screen.blit(ctr_surf, (r.x + (r.width - ctr_surf.get_width()) // 2, r.bottom - 13))
            if rects.get("recenter_all"):
                is_picking = self.active_tool == "recenter_pick"
                ic = (200, 170, 240) if is_picking else _ICON
                eye_surf = self._toolbar_font.render("VIEW", True, ic)
                r = rects["recenter_all"]
                screen.blit(eye_surf, (r.x + (r.width - eye_surf.get_width()) // 2, r.bottom - 13))
            if rects.get("reveal"):
                is_reveal = self.active_tool == "reveal"
                ic = (240, 210, 100) if is_reveal else _ICON
                rev_surf = self._toolbar_font.render("RVEAL", True, ic)
                r = rects["reveal"]
                screen.blit(rev_surf, (r.x + (r.width - rev_surf.get_width()) // 2, r.bottom - 13))

    # ------------------------------------------------------------------
    # Highlight rendering
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Fog of war
    # ------------------------------------------------------------------

    def _update_los(self):
        """Recompute the current LOS set from the player's token position."""
        if not self.map_data or not self._player_name:
            self._current_los = set()
            return
        token = next((c for c in self.server.combatants
                      if c.name == self._player_name and c.pos), None)
        if not token:
            self._current_los = set()
            return
        self._current_los = compute_los(
            self.map_data, token.pos, self.server.visibility_radius,
            self._player_door_states,       # use last-seen states so fog gates LOS too
            self._player_iron_door_states,
            self.server.secret_door_states,
        )
        # For each newly visible tile, learn its current door state
        for (c, r) in self._current_los:
            k = (r, c)
            if k in self.server.door_states:
                self._player_door_states[k] = self.server.door_states[k]
            if k in self.server.iron_door_states:
                self._player_iron_door_states[k] = self.server.iron_door_states[k]
        # Accumulate into local explored set (server is authoritative but this keeps
        # rendering smooth without waiting for the server round-trip)
        self._explored_tiles.update(self._current_los)

    def _draw_fog(self, screen):
        """
        Overlay fog of war on the map.
        Unexplored tiles → solid black.
        Explored but not currently visible → dark semi-transparent overlay.
        Currently visible → no overlay (clear).
        """
        if not self.map_data:
            return
        rows = len(self.map_data)
        cols = len(self.map_data[0]) if rows else 0
        ts = self.tile_size

        # Build a surface that covers the entire map area
        map_w = cols * ts
        map_h = rows * ts
        fog = pygame.Surface((map_w, map_h), pygame.SRCALPHA)

        BLACK      = (0,   0,   0, 255)
        MEMORY     = (0,   0,   0, 50)

        for row in range(rows):
            for col in range(cols):
                x = col * ts
                y = row * ts
                tile = (col, row)
                if tile in self._current_los:
                    pass  # fully visible — no overlay
                elif tile in self._explored_tiles:
                    pygame.draw.rect(fog, MEMORY, (x, y, ts, ts))
                else:
                    pygame.draw.rect(fog, BLACK, (x, y, ts, ts))

        screen.blit(fog, (self.offset_x, self.offset_y))

    def _draw_highlights(self, screen):
        """Draw flickering square border glows for all active tile highlights."""
        if not self.server.tile_highlights:
            return
        t = pygame.time.get_ticks()
        # ~1 Hz flicker: sin period = 2π / 0.00628 ≈ 1000 ms
        flicker = 0.5 + 0.5 * math.sin(t * 0.00628)
        alpha = int(80 + 160 * flicker)   # 80 … 240
        inset = 2
        border = 3
        for h in self.server.tile_highlights:
            col, row = h["pos"]
            x = col * self.tile_size + self.offset_x
            y = row * self.tile_size + self.offset_y
            if x + self.tile_size < 0 or y + self.tile_size < 0:
                continue
            if x > screen.get_width() or y > screen.get_height():
                continue
            rgb = _ALL_COLORS.get(h["color"], (255, 200, 0))
            surf = pygame.Surface((self.tile_size, self.tile_size), pygame.SRCALPHA)
            pygame.draw.rect(surf, (*rgb, alpha),
                             (inset, inset,
                              self.tile_size - 2 * inset,
                              self.tile_size - 2 * inset),
                             border)
            screen.blit(surf, (x, y))

    # ------------------------------------------------------------------
    # Map rendering
    # ------------------------------------------------------------------

    def draw_map(self, screen):
        # In player mode use fog-gated door states so doors only visually change
        # when the player has LOS on them.
        door_st = self._player_door_states if self._player_name else self.server.door_states
        iron_st = self._player_iron_door_states if self._player_name else self.server.iron_door_states
        for row in range(len(self.map_data)):
            for col in range(len(self.map_data[0])):
                x = col * self.tile_size + self.offset_x
                y = row * self.tile_size + self.offset_y
                tile = self.map_data[row][col]
                key = (row, col)

                if tile == 0:   # nothing / void
                    pygame.draw.rect(screen, (0, 0, 0), (x, y, self.tile_size, self.tile_size))
                elif tile == 1:  # floor
                    screen.blit(self.floor_texture, (x, y))
                elif tile == 2:  # wall
                    screen.blit(self.wall_texture, (x, y))
                elif tile == 3:  # wooden door
                    screen.blit(self.floor_texture, (x, y))
                    if door_st.get(key) == "open":
                        screen.blit(self.wooden_door_open_texture, (x, y))
                    else:
                        screen.blit(self.wooden_door_closed_texture, (x, y))
                elif tile == 4:  # iron door
                    screen.blit(self.floor_texture, (x, y))
                    if iron_st.get(key) == "open":
                        screen.blit(self.iron_door_open_texture, (x, y))
                    else:
                        screen.blit(self.iron_door_closed_texture, (x, y))
                elif tile == 5:  # secret door — looks like wall until revealed
                    screen.blit(self.wall_texture, (x, y))
                    if self.server.secret_door_states.get(key) == "open":
                        screen.blit(self.iron_door_open_texture, (x, y))
                elif tile == 6:  # trap — looks like floor until revealed
                    screen.blit(self.floor_texture, (x, y))
                    if self.server.trap_states.get(key) == "open":
                        screen.blit(self.trap_texture, (x, y))

    def draw_grid(self, screen):
        if not self.map_data:
            return
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
            is_dead = "Dead" in c.conditions
            if icon_file and icon_file in self.icons:
                surf = pygame.transform.grayscale(self.icons[icon_file]) if is_dead else self.icons[icon_file]
                screen.blit(surf, (x, y))
            else:
                color = (160, 160, 160) if is_dead else (255, 0, 0)
                pygame.draw.circle(screen, color, (x + self.tile_size // 2, y + self.tile_size // 2), self.tile_size // 3)

            # Highlight selected (DM local selection — gold)
            if c == selected_token:
                pygame.draw.rect(screen, (255, 200, 0), pygame.Rect(x, y, self.tile_size, self.tile_size), 3)

            # Highlight remote player selections (each with their own color)
            offset = 0
            for selector, (token_name, color_name) in self._remote_selections.items():
                if c.name == token_name:
                    rgb = _ALL_COLORS.get(color_name, (255, 255, 255))
                    pygame.draw.rect(screen, rgb,
                                     pygame.Rect(x - offset, y - offset,
                                                 self.tile_size + offset * 2,
                                                 self.tile_size + offset * 2), 3)
                    offset += 4  # stack multiple selections outward

            # Highlight active — gold pulsing glow
            if active_combatant and c == active_combatant:
                glow_radius = self.tile_size // 4 + int((self.tile_size//8) * (1 + math.sin(pygame.time.get_ticks() * 0.005)))
                glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
                pygame.draw.circle(glow_surface, (255, 200, 0, 120), (glow_radius, glow_radius), glow_radius)
                screen.blit(glow_surface, (x + self.tile_size // 2 - glow_radius, y + self.tile_size // 2 - glow_radius))

    # ------------------------------------------------------------------
    # Minimap
    # ------------------------------------------------------------------

    def _build_minimap_surface(self):
        if not self.map_data:
            return
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        # Fixed 2.4 px per tile (= 60 * 0.04) — independent of zoom level
        mini_w = max(1, int(cols * 2.4))
        mini_h = max(1, int(rows * 2.4))

        # Draw one pixel per tile, then scale up — avoids float-rounding grid artefacts
        pixel_surf = pygame.Surface((cols, rows))
        for row in range(rows):
            for col in range(cols):
                tile = self.map_data[row][col]
                if tile == 0:
                    color = (0, 0, 0)
                elif tile == 2:
                    color = (100, 60, 40)
                else:
                    color = (210, 210, 200)
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

    def _confirm_quit(self):
        """Pygame-native yes/no dialog — safe to call from any thread on any OS."""
        screen = pygame.display.get_surface()
        sw, sh = screen.get_size()

        # Dim overlay
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        screen.blit(overlay, (0, 0))

        font_big = pygame.font.SysFont('Arial', 20, bold=True)
        font_btn = pygame.font.SysFont('Arial', 16)

        msg   = font_big.render('Quit DungeonPy?', True, (230, 230, 230))
        yes_t = font_btn.render('Yes', True, (230, 230, 230))
        no_t  = font_btn.render('No',  True, (230, 230, 230))

        box_w, box_h = 280, 120
        bx = (sw - box_w) // 2
        by = (sh - box_h) // 2
        pygame.draw.rect(screen, (40, 40, 50), (bx, by, box_w, box_h), border_radius=8)
        pygame.draw.rect(screen, (90, 90, 110), (bx, by, box_w, box_h), 2, border_radius=8)
        screen.blit(msg, (bx + (box_w - msg.get_width()) // 2, by + 18))

        yes_rect = pygame.Rect(bx + 40,  by + 68, 80, 32)
        no_rect  = pygame.Rect(bx + 160, by + 68, 80, 32)
        pygame.draw.rect(screen, (160, 50, 50),  yes_rect, border_radius=5)
        pygame.draw.rect(screen, (55, 55, 70),   no_rect,  border_radius=5)
        screen.blit(yes_t, yes_rect.move((yes_rect.w - yes_t.get_width()) // 2,
                                         (yes_rect.h - yes_t.get_height()) // 2).topleft)
        screen.blit(no_t,  no_rect.move((no_rect.w  - no_t.get_width())  // 2,
                                         (no_rect.h  - no_t.get_height())  // 2).topleft)
        pygame.display.flip()

        while True:
            for ev in pygame.event.get():
                if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    if yes_rect.collidepoint(ev.pos):
                        return True
                    if no_rect.collidepoint(ev.pos):
                        return False
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_RETURN:
                        return True
                    if ev.key == pygame.K_ESCAPE:
                        return False
                if ev.type == pygame.QUIT:
                    return True

    def run_loop(self, screen):
        clock = pygame.time.Clock()
        while self.running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    if self._confirm_quit():
                        self.running = False

                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        if self._confirm_quit():
                            self.running = False

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    if event.button == 1:
                        self.handle_click(event.pos, 1)
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
            (self.floor_texture, self.wall_texture, self.wooden_door_closed_texture,
             self.wooden_door_open_texture, self.iron_door_closed_texture,
             self.iron_door_open_texture, self.secret_door_texture,
             self.trap_texture) = self.scale_textures(self.tile_size)
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

        # Toolbar takes priority — all buttons live in the right strip
        if button == 1:
            screen_w = pygame.display.get_surface().get_width()
            if mx >= screen_w - TOOLBAR_WIDTH:
                self._handle_toolbar_click(mx, my)
                return

        if button == 1:
            minimap = self._minimap_rect()
            if minimap and minimap.collidepoint(mx, my):
                self._recenter_on_minimap_click(mx, my)
                return

        col = (mx - self.offset_x) // self.tile_size
        row = (my - self.offset_y) // self.tile_size

        # Recenter-pick mode — DM clicks a tile to recenter all players there
        if button == 1 and self.active_tool == "recenter_pick":
            if 0 <= row < len(self.map_data) and 0 <= col < len(self.map_data[0]):
                self._submit({"action": "recenter_all", "pos": [col, row]})
            self.active_tool = "select"
            return

        # Reveal mode — DM clicks a secret door tile to reveal it to nearby players
        if button == 1 and self.active_tool == "reveal":
            if 0 <= row < len(self.map_data) and 0 <= col < len(self.map_data[0]):
                self._submit({"action": "reveal_secret_door", "pos": [col, row]})
            self.active_tool = "select"
            return

        # Highlight tool — toggle tile and skip all selection/placement logic
        if button == 1 and self.active_tool == "highlight":
            if 0 <= row < len(self.map_data) and 0 <= col < len(self.map_data[0]):
                if self._player_name:
                    self._submit({"action": "highlight_tile", "pos": [col, row]})
                else:
                    self._submit({"action": "highlight_tile", "pos": [col, row],
                                  "owner": "DM", "color": "gold"})
            return

        if self.verbose:
            log(f"[Map] Mouse click at pixel=({mx},{my}) tile=({col},{row})")

        if button == 1:
            if self.super_verbose:
                for c in self.server.combatants:
                    if c.pos:
                        cx, cy = c.pos
                        x = cx * self.tile_size + self.offset_x
                        y = cy * self.tile_size + self.offset_y
                        rect = pygame.Rect(x, y, self.tile_size, self.tile_size)
                        log(f"[Map] Checking token {c.name} at tile {c.pos} -> pixel ({x},{y})")
                        log(f"rect: {rect}, tile size: {self.tile_size}, offset: ({self.offset_x}, {self.offset_y})")

            # Tokens have priority: check for a token before checking the tile type.
            # This ensures a token placed on a door can still be selected.
            token = self.get_token_at_pixel(mx, my)
            hit = token is not None
            if token:
                self._submit({"action": "select", "name": token.name})
                if self.verbose:
                    log(f"[Map] Selected token: {token.name}")

            if not hit and 0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data):
                tile = self.map_data[row][col]
                if tile in (3, 4, 5, 6):
                    self._submit({"action": "toggle_door", "x": col, "y": row, "tile_type": tile})
                    if self.verbose:
                        log(f"[Map] Toggled door at ({col}, {row})")
                    return

            if not hit and self.unplaced and self._is_placeable(col, row):
                combatant = self.unplaced[0]  # peek; handle_server_event removes it on token_placed
                self._submit({"action": "place_token", "name": combatant.name, "pos": [col, row]})
                self._submit({"action": "select", "name": combatant.name})
                if self.verbose:
                    log(f"[Map] Placed new token: {combatant.name} at ({col},{row})")
                hit = True

            if not hit:
                if self.verbose:
                    log(f"[Map] No token selected")
                self._submit({"action": "clear_selection"})

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
        if self.active_tool != "select":
            return None
        screen_w = pygame.display.get_surface().get_width()
        if mx >= screen_w - TOOLBAR_WIDTH:
            return None
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

        if (self._is_placeable(col, row)
                and not self.is_tile_occupied(col, row, ignore_token=self.dragging_token)):
            self._submit({"action": "move_token", "name": self.dragging_token.name, "pos": [col, row]})
            if self.verbose:
                log(f"[Map] Dropped token {self.dragging_token.name} at ({col},{row})")
        else:
            self._submit({"action": "move_token", "name": self.dragging_token.name, "pos": self.initial_token_pos})
            if self.verbose:
                log(f"[Map] Invalid drop, reverted {self.dragging_token.name} to {self.initial_token_pos}")

        self.dragging_token = None
        self.drag_candidate = None
        self.initial_token_pos = None

    def _is_placeable(self, col, row):
        """Return True for passable tiles; secret doors only if already revealed."""
        if not (0 <= col < len(self.map_data[0]) and 0 <= row < len(self.map_data)):
            return False
        tile = self.map_data[row][col]
        if tile in (0, 2):  # nothing, wall
            return False
        if tile == 5:  # secret door — only placeable once revealed
            return self.server.secret_door_states.get((row, col)) == "open"
        return True

    def get_pixel_coords(self, grid_pos):
        cx, cy = grid_pos
        return cx * self.tile_size + self.offset_x, cy * self.tile_size + self.offset_y
