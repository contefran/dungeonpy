#!/usr/bin/env python3
"""
map_editor.py — Standalone DungeonPy map editor.

Paint tiles on a grid and save the result as a .txt file readable by DungeonPy.
Run from the project root:
    python3 map_editor.py [existing_map.txt]
"""

import copy
import os
import sys
import threading

import pygame
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

# ── Tile codes (match MapManager.draw_map) ───────────────────────────────────
VOID        = 0
FLOOR       = 1
WALL        = 2
WOODEN_DOOR = 3
IRON_DOOR   = 4
SECRET_DOOR = 5
TRAP        = 6
GRASS       = 16   # 'g' in txt

TILE_TO_CHAR = {
    VOID: '0', FLOOR: '1', WALL: '2', WOODEN_DOOR: '3',
    IRON_DOOR: '4', SECRET_DOOR: '5', TRAP: '6', GRASS: 'g',
}
TILE_LABELS = [
    (FLOOR,       "Floor"),
    (WALL,        "Wall"),
    (VOID,        "Void"),
    (WOODEN_DOOR, "W.Door"),
    (IRON_DOOR,   "I.Door"),
    (SECRET_DOOR, "Secret"),
    (TRAP,        "Trap"),
    (GRASS,       "Grass"),
]
FALLBACK_COLORS = {
    VOID: (0, 0, 0), FLOOR: (120, 100, 80), WALL: (60, 60, 70),
    WOODEN_DOOR: (139, 90, 43), IRON_DOOR: (100, 100, 120),
    SECRET_DOOR: (60, 60, 70), TRAP: (80, 60, 60), GRASS: (60, 120, 40),
}

TOOLBAR_W  = 112
UNDO_LIMIT = 60
ACTION_BUTTONS = [
    ("New",     "Ctrl+N"),
    ("Open",    "Ctrl+O"),
    ("Save",    "Ctrl+S"),
    ("Save As", "Ctrl+Shift+S"),
    ("Undo",    "Ctrl+Z"),
    ("Redo",    "Ctrl+Y"),
]


# ── I/O helpers ──────────────────────────────────────────────────────────────

def _parse_char(ch):
    if ch.isdigit():
        return int(ch)
    if ch.isalpha():
        return ord(ch.lower()) - ord('a') + 10
    return VOID


def load_txt(path):
    with open(path) as f:
        lines = f.readlines()
    return [[_parse_char(ch) for ch in line.strip()] for line in lines if line.strip()]


def save_txt(map_data, path):
    rows = [''.join(TILE_TO_CHAR.get(t, '0') for t in row) for row in map_data]
    with open(path, 'w') as f:
        f.write('\n'.join(rows) + '\n')


def empty_map(cols, rows):
    return [[VOID] * cols for _ in range(rows)]


def _ask_new_dimensions():
    """Show tkinter dialogs to get map size. Called before pygame.display.set_mode()
    so the dialogs are not hidden behind the pygame window."""
    root = tk.Tk()
    root.withdraw()
    root.lift()
    cols = simpledialog.askinteger("New map", "Width (columns)?",
                                   initialvalue=20, minvalue=2, maxvalue=300, parent=root)
    rows = simpledialog.askinteger("New map", "Height (rows)?",
                                   initialvalue=20, minvalue=2, maxvalue=300, parent=root)
    root.destroy()
    return cols, rows


# ── Editor ───────────────────────────────────────────────────────────────────

class MapEditor:

    def __init__(self, dir_path, initial_file=None):
        self.dir_path  = dir_path
        self.tile_size = 40
        self.offset_x  = TOOLBAR_W
        self.offset_y  = 0
        self.map_data  = []
        self.save_path = None

        self._sel_tile   = FLOOR
        self._paint_mode = 'free'    # 'free' | 'rect'
        self._painting   = False
        self._paint_tile = None
        self._last_cell  = None
        self._rect_start = None
        self._rect_end   = None
        self._panning    = False
        self._pan_start  = (0, 0)
        self._undo_stack = []
        self._redo_stack = []

        # Ask for dimensions BEFORE pygame creates its window so the dialog
        # is not hidden behind a pygame surface.
        if initial_file and os.path.isfile(initial_file):
            init_data      = load_txt(initial_file)
            self.save_path = initial_file
        else:
            cols, rows = _ask_new_dimensions()
            if not cols or not rows:
                sys.exit(0)
            init_data = empty_map(cols, rows)

        pygame.init()
        self._screen = pygame.display.set_mode((1280, 800), pygame.RESIZABLE)
        pygame.display.set_caption(
            f"DungeonPy Map Editor — {os.path.basename(self.save_path)}"
            if self.save_path else "DungeonPy Map Editor — unsaved")
        self._font = pygame.font.SysFont(None, 19)

        self._tex_orig = {}
        self._tex      = {}
        self._load_textures()

        self.map_data = init_data
        self._center_map()

    # ── Textures ─────────────────────────────────────────────────────────────

    def _load_textures(self):
        d = self.dir_path
        def _img(rel, alpha=False):
            p = os.path.join(d, rel)
            if not os.path.isfile(p):
                return None
            try:
                s = pygame.image.load(p)
                return s.convert_alpha() if alpha else s.convert()
            except Exception:
                return None

        wall = _img('Assets/Textures/stonefloor4.jpg')
        self._tex_orig = {
            FLOOR:       _img('Assets/Textures/stonefloor3.jpg'),
            WALL:        wall,
            WOODEN_DOOR: _img('Assets/Textures/Wooden_door_closed.png', alpha=True),
            IRON_DOOR:   _img('Assets/Textures/Iron_door_closed.png',   alpha=True),
            SECRET_DOOR: wall,
            TRAP:        _img('Assets/Textures/trap_pit.jpg', alpha=True),
            GRASS:       _img('Assets/Textures/grass_4.png'),
        }
        self._rescale_textures()

    def _rescale_textures(self):
        ts = self.tile_size
        self._tex = {
            t: pygame.transform.scale(orig, (ts, ts))
            for t, orig in self._tex_orig.items() if orig is not None
        }

    # ── Map helpers ───────────────────────────────────────────────────────────

    def _center_map(self):
        if not self.map_data:
            return
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        w, h = self._screen.get_size()
        self.offset_x = TOOLBAR_W + max(0, (w - TOOLBAR_W - cols * self.tile_size) // 2)
        self.offset_y = max(0, (h - rows * self.tile_size) // 2)

    def _cell(self, px, py):
        if not self.map_data:
            return None
        c = (px - self.offset_x) // self.tile_size
        r = (py - self.offset_y) // self.tile_size
        if 0 <= r < len(self.map_data) and 0 <= c < len(self.map_data[0]):
            return r, c
        return None

    # ── Undo / redo ───────────────────────────────────────────────────────────

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self.map_data))
        if len(self._undo_stack) > UNDO_LIMIT:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def _undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(copy.deepcopy(self.map_data))
        self.map_data = self._undo_stack.pop()

    def _redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(copy.deepcopy(self.map_data))
        self.map_data = self._redo_stack.pop()

    # ── Dialogs ───────────────────────────────────────────────────────────────

    @staticmethod
    def _tk():
        r = tk.Tk()
        r.withdraw()
        r.lift()
        return r

    def _dialog(self, fn):
        """Run a blocking tkinter dialog fn() while pumping pygame events in the
        background so the WM doesn't mark the window as 'not responding'."""
        stop = threading.Event()
        def _pump():
            while not stop.is_set():
                try:
                    pygame.event.pump()
                except Exception:
                    pass
                pygame.time.wait(50)
        t = threading.Thread(target=_pump, daemon=True)
        t.start()
        try:
            return fn()
        finally:
            stop.set()
            t.join(timeout=1)

    def _do_new(self):
        cols, rows = self._dialog(_ask_new_dimensions)
        if cols and rows:
            self.map_data  = empty_map(cols, rows)
            self.save_path = None
            self._undo_stack.clear()
            self._redo_stack.clear()
            pygame.display.set_caption("DungeonPy Map Editor — unsaved")
            self._center_map()

    def _do_open(self):
        maps_dir = os.path.join(self.dir_path, 'Maps')
        root = self._tk()
        path = self._dialog(lambda: filedialog.askopenfilename(
            title="Open map",
            initialdir=maps_dir if os.path.isdir(maps_dir) else self.dir_path,
            filetypes=[("Map files", "*.txt"), ("All files", "*.*")],
            parent=root,
        ))
        root.destroy()
        if path:
            self.map_data  = load_txt(path)
            self.save_path = path
            self._undo_stack.clear()
            self._redo_stack.clear()
            pygame.display.set_caption(
                f"DungeonPy Map Editor — {os.path.basename(path)}")
            self._center_map()

    def _do_save(self, force_dialog=False):
        if not self.map_data:
            return
        if force_dialog or not self.save_path:
            maps_dir = os.path.join(self.dir_path, 'Maps')
            root = self._tk()
            path = self._dialog(lambda: filedialog.asksaveasfilename(
                title="Save map",
                initialdir=maps_dir if os.path.isdir(maps_dir) else self.dir_path,
                defaultextension=".txt",
                filetypes=[("Map files", "*.txt"), ("All files", "*.*")],
                parent=root,
            ))
            root.destroy()
            if not path:
                return
            self.save_path = path
        save_txt(self.map_data, self.save_path)
        pygame.display.set_caption(
            f"DungeonPy Map Editor — {os.path.basename(self.save_path)}")

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _blit_tile(self, screen, tile, x, y):
        ts = self.tile_size
        if tile == VOID:
            pygame.draw.rect(screen, (0, 0, 0), (x, y, ts, ts))
            return
        if tile in (WOODEN_DOOR, IRON_DOOR, SECRET_DOOR, TRAP):
            if FLOOR in self._tex:
                screen.blit(self._tex[FLOOR], (x, y))
            else:
                pygame.draw.rect(screen, FALLBACK_COLORS[FLOOR], (x, y, ts, ts))
        if tile in self._tex:
            screen.blit(self._tex[tile], (x, y))
        else:
            pygame.draw.rect(screen, FALLBACK_COLORS.get(tile, (80, 80, 80)), (x, y, ts, ts))

    def _draw_map(self, screen):
        for r, row in enumerate(self.map_data):
            for c, tile in enumerate(row):
                self._blit_tile(screen, tile,
                                c * self.tile_size + self.offset_x,
                                r * self.tile_size + self.offset_y)

    def _draw_grid(self, screen):
        if self.tile_size < 8 or not self.map_data:
            return
        rows = len(self.map_data)
        cols = len(self.map_data[0])
        color = (55, 55, 55)
        x0, y0, ts = self.offset_x, self.offset_y, self.tile_size
        for c in range(cols + 1):
            x = x0 + c * ts
            pygame.draw.line(screen, color, (x, y0), (x, y0 + rows * ts))
        for r in range(rows + 1):
            y = y0 + r * ts
            pygame.draw.line(screen, color, (x0, y), (x0 + cols * ts, y))

    def _draw_hover(self, screen):
        ts = self.tile_size
        if self._paint_mode == 'rect' and self._rect_start and self._rect_end:
            r0, c0 = self._rect_start
            r1, c1 = self._rect_end
            rmin, rmax = min(r0, r1), max(r0, r1)
            cmin, cmax = min(c0, c1), max(c0, c1)
            fill = pygame.Surface((ts, ts), pygame.SRCALPHA)
            pygame.draw.rect(fill, (255, 255, 255, 55), (0, 0, ts, ts))
            for rr in range(rmin, rmax + 1):
                for cc in range(cmin, cmax + 1):
                    screen.blit(fill, (cc * ts + self.offset_x, rr * ts + self.offset_y))
            px = cmin * ts + self.offset_x
            py = rmin * ts + self.offset_y
            pygame.draw.rect(screen, (255, 220, 80),
                             (px, py, (cmax - cmin + 1) * ts, (rmax - rmin + 1) * ts), 2)
        else:
            mx, my = pygame.mouse.get_pos()
            cell = self._cell(mx, my)
            if not cell:
                return
            r, c = cell
            surf = pygame.Surface((ts, ts), pygame.SRCALPHA)
            pygame.draw.rect(surf, (255, 255, 255, 60), (0, 0, ts, ts))
            screen.blit(surf, (c * ts + self.offset_x, r * ts + self.offset_y))

    def _draw_toolbar(self, screen):
        _, h = self._screen.get_size()
        pygame.draw.rect(screen, (38, 38, 44), (0, 0, TOOLBAR_W, h))

        btn_h  = 42
        margin = 5

        # ── Tile type buttons ────────────────────────────────────────────────
        for i, (tile, label) in enumerate(TILE_LABELS):
            y    = margin + i * (btn_h + margin)
            rect = pygame.Rect(margin, y, TOOLBAR_W - 2 * margin, btn_h)
            pygame.draw.rect(screen,
                             (75, 120, 200) if tile == self._sel_tile else (55, 55, 62),
                             rect, border_radius=4)
            sw = 26
            sx, sy = rect.x + 4, rect.y + (btn_h - sw) // 2
            pygame.draw.rect(screen, (0, 0, 0), (sx, sy, sw, sw))
            if tile != VOID and tile in self._tex_orig and self._tex_orig[tile]:
                screen.blit(pygame.transform.scale(self._tex_orig[tile], (sw, sw)), (sx, sy))
            lbl = self._font.render(label, True, (215, 215, 215))
            screen.blit(lbl, (sx + sw + 5, sy + (sw - lbl.get_height()) // 2))

        # ── Separator ────────────────────────────────────────────────────────
        sep_y = margin + len(TILE_LABELS) * (btn_h + margin) + 6
        pygame.draw.line(screen, (65, 65, 75), (margin, sep_y), (TOOLBAR_W - margin, sep_y))

        # ── Paint mode toggle ────────────────────────────────────────────────
        mode_y = sep_y + 8
        mode_w = (TOOLBAR_W - 2 * margin - 3) // 2
        for mi, (mode_id, mode_lbl) in enumerate([('free', 'Free'), ('rect', 'Rect')]):
            mrect = pygame.Rect(margin + mi * (mode_w + 3), mode_y, mode_w, 24)
            pygame.draw.rect(screen,
                             (75, 150, 80) if self._paint_mode == mode_id else (52, 52, 60),
                             mrect, border_radius=3)
            ms = self._font.render(mode_lbl, True, (220, 220, 220))
            screen.blit(ms, (mrect.x + (mrect.w - ms.get_width()) // 2,
                              mrect.y + (mrect.h - ms.get_height()) // 2))

        sep2_y = mode_y + 24 + 6
        pygame.draw.line(screen, (65, 65, 75), (margin, sep2_y), (TOOLBAR_W - margin, sep2_y))

        # ── Action buttons ───────────────────────────────────────────────────
        act_h = 25
        for j, (label, _) in enumerate(ACTION_BUTTONS):
            y    = sep2_y + 8 + j * (act_h + 3)
            rect = pygame.Rect(margin, y, TOOLBAR_W - 2 * margin, act_h)
            pygame.draw.rect(screen, (52, 52, 60), rect, border_radius=3)
            lbl = self._font.render(label, True, (195, 195, 195))
            screen.blit(lbl, (rect.x + (rect.w - lbl.get_width()) // 2,
                               rect.y + (rect.h - lbl.get_height()) // 2))

        # ── Coordinates ──────────────────────────────────────────────────────
        cell = self._cell(*pygame.mouse.get_pos())
        if cell:
            r, c = cell
            coord = self._font.render(f"col {c}  row {r}", True, (120, 120, 130))
            screen.blit(coord, (4, h - coord.get_height() - 6))

        pygame.draw.line(screen, (70, 70, 80), (TOOLBAR_W, 0), (TOOLBAR_W, h))

    def _toolbar_hit(self, x, y):
        if x >= TOOLBAR_W:
            return False

        btn_h  = 42
        margin = 5

        for i, (tile, _) in enumerate(TILE_LABELS):
            ty = margin + i * (btn_h + margin)
            if ty <= y <= ty + btn_h:
                self._sel_tile = tile
                return True

        sep_y  = margin + len(TILE_LABELS) * (btn_h + margin) + 6
        mode_y = sep_y + 8
        mode_w = (TOOLBAR_W - 2 * margin - 3) // 2
        for mi, mode_id in enumerate(['free', 'rect']):
            mx_ = margin + mi * (mode_w + 3)
            if mx_ <= x <= mx_ + mode_w and mode_y <= y <= mode_y + 24:
                self._paint_mode = mode_id
                return True

        sep2_y = mode_y + 24 + 6
        act_h  = 25
        actions = [
            self._do_new,
            self._do_open,
            lambda: self._do_save(False),
            lambda: self._do_save(True),
            self._undo,
            self._redo,
        ]
        for j, fn in enumerate(actions):
            ay = sep2_y + 8 + j * (act_h + 3)
            if ay <= y <= ay + act_h:
                fn()
                return True

        return True

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        clock = pygame.time.Clock()

        while True:
            for event in pygame.event.get():

                if event.type == pygame.QUIT:
                    root = self._tk()
                    if self._dialog(lambda: messagebox.askyesno(
                            "Quit", "Quit the map editor?", parent=root)):
                        root.destroy()
                        pygame.quit()
                        return
                    root.destroy()

                elif event.type == pygame.VIDEORESIZE:
                    self._screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)

                elif event.type == pygame.KEYDOWN:
                    ctrl  = event.mod & pygame.KMOD_CTRL
                    shift = event.mod & pygame.KMOD_SHIFT
                    if ctrl and event.key == pygame.K_z:
                        self._redo() if shift else self._undo()
                    elif ctrl and event.key == pygame.K_y:
                        self._redo()
                    elif ctrl and event.key == pygame.K_s:
                        self._do_save(force_dialog=shift)
                    elif ctrl and event.key == pygame.K_o:
                        self._do_open()
                    elif ctrl and event.key == pygame.K_n:
                        self._do_new()

                elif event.type == pygame.MOUSEBUTTONDOWN:
                    x, y = event.pos
                    if event.button == 1:
                        if not self._toolbar_hit(x, y):
                            cell = self._cell(x, y)
                            if cell:
                                if self._paint_mode == 'rect':
                                    self._painting   = True
                                    self._paint_tile = self._sel_tile
                                    self._rect_start = cell
                                    self._rect_end   = cell
                                else:
                                    self._push_undo()
                                    self._painting   = True
                                    self._paint_tile = self._sel_tile
                                    r, c = cell
                                    self.map_data[r][c] = self._paint_tile
                                    self._last_cell = cell
                    elif event.button == 3:
                        self._panning   = True
                        self._pan_start = event.pos

                elif event.type == pygame.MOUSEBUTTONUP:
                    if event.button == 1:
                        if self._paint_mode == 'rect' and self._painting and self._rect_start:
                            self._push_undo()
                            r0, c0 = self._rect_start
                            r1, c1 = self._rect_end or self._rect_start
                            for rr in range(min(r0, r1), max(r0, r1) + 1):
                                for cc in range(min(c0, c1), max(c0, c1) + 1):
                                    self.map_data[rr][cc] = self._paint_tile
                            self._rect_start = None
                            self._rect_end   = None
                        self._painting = False
                    elif event.button == 3:
                        self._panning = False

                elif event.type == pygame.MOUSEMOTION:
                    x, y = event.pos
                    if self._panning:
                        dx = x - self._pan_start[0]
                        dy = y - self._pan_start[1]
                        self.offset_x += dx
                        self.offset_y += dy
                        self._pan_start = (x, y)
                    elif self._painting:
                        cell = self._cell(x, y)
                        if cell:
                            if self._paint_mode == 'rect':
                                self._rect_end = cell
                            elif cell != self._last_cell:
                                r, c = cell
                                self.map_data[r][c] = self._paint_tile
                                self._last_cell = cell

                elif event.type == pygame.MOUSEWHEEL:
                    old = self.tile_size
                    self.tile_size = max(8, min(120, self.tile_size + event.y * 2))
                    if self.tile_size != old:
                        mx, my = pygame.mouse.get_pos()
                        scale = self.tile_size / old
                        self.offset_x = int(mx - (mx - self.offset_x) * scale)
                        self.offset_y = int(my - (my - self.offset_y) * scale)
                        self._rescale_textures()

            self._screen.fill((18, 18, 22))
            self._draw_map(self._screen)
            self._draw_grid(self._screen)
            self._draw_hover(self._screen)
            self._draw_toolbar(self._screen)
            pygame.display.flip()
            clock.tick(60)


def main():
    dir_path     = os.path.dirname(os.path.abspath(__file__))
    initial_file = sys.argv[1] if len(sys.argv) > 1 else None
    MapEditor(dir_path=dir_path, initial_file=initial_file).run()


if __name__ == "__main__":
    main()
