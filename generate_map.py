"""
generate_map.py — Procedural dungeon map generator for DungeonPy.

Tile codes (new numbering):
  0 = void / nothing (exterior)
  1 = floor
  2 = wall
  3 = wooden door
  4 = iron door
  5 = secret door (looks like wall until clicked)
  6 = trap       (looks like floor until clicked)

Usage:
    python3 generate_map.py [--seed N]
"""

import argparse
import os
import random
import sys
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class Room:
    x: int   # left column (grid col)
    y: int   # top row    (grid row)
    w: int   # width  in tiles
    h: int   # height in tiles
    id: int


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def room_center(room: Room):
    return room.x + room.w // 2, room.y + room.h // 2


def room_center_dist(r1: Room, r2: Room) -> int:
    cx1, cy1 = room_center(r1)
    cx2, cy2 = room_center(r2)
    return abs(cx1 - cx2) + abs(cy1 - cy2)


def rooms_overlap(r1: Room, r2: Room, gap: int = 1) -> bool:
    """AABB overlap test with an extra gap on all sides."""
    return not (
        r1.x + r1.w + gap <= r2.x or
        r2.x + r2.w + gap <= r1.x or
        r1.y + r1.h + gap <= r2.y or
        r2.y + r2.h + gap <= r1.y
    )


# ---------------------------------------------------------------------------
# Step 1 — Room placement
# ---------------------------------------------------------------------------

def place_rooms(width, height, num_rooms,
                room_min_w=5, room_min_h=5,
                room_max_w=12, room_max_h=12,
                max_retries=200):
    rooms: list[Room] = []
    room_cells: set[tuple] = set()

    for i in range(num_rooms):
        placed = False
        for _ in range(max_retries):
            rw = random.randint(room_min_w, room_max_w)
            rh = random.randint(room_min_h, room_max_h)
            # Keep at least 1 tile of void border on all sides
            if rw > width - 4 or rh > height - 4:
                continue
            x = random.randint(2, width  - rw - 2)
            y = random.randint(2, height - rh - 2)
            candidate = Room(x=x, y=y, w=rw, h=rh, id=len(rooms))
            if any(rooms_overlap(candidate, other) for other in rooms):
                continue
            rooms.append(candidate)
            for row in range(y, y + rh):
                for col in range(x, x + rw):
                    room_cells.add((row, col))
            placed = True
            break

        if not placed:
            print(f"  Warning: could only place {len(rooms)} of {num_rooms} rooms "
                  f"(ran out of space).", file=sys.stderr)
            break

    return rooms, room_cells


# ---------------------------------------------------------------------------
# Step 2 — Minimum spanning tree (Prim's, Manhattan distance)
# ---------------------------------------------------------------------------

def build_mst(rooms: list[Room]) -> list[tuple]:
    if len(rooms) < 2:
        return []
    in_tree = {0}
    edges = []
    while len(in_tree) < len(rooms):
        best_dist = float('inf')
        best_edge = None
        for a in in_tree:
            for b in range(len(rooms)):
                if b in in_tree:
                    continue
                d = room_center_dist(rooms[a], rooms[b])
                if d < best_dist:
                    best_dist = d
                    best_edge = (a, b)
        if best_edge is None:
            break
        edges.append(best_edge)
        in_tree.add(best_edge[1])
    return edges


# ---------------------------------------------------------------------------
# Step 3 — Corridor carving (L-shaped)
# ---------------------------------------------------------------------------

def _carve_h(row, col_a, col_b, room_cells, corridor_cells):
    for col in range(min(col_a, col_b), max(col_a, col_b) + 1):
        if (row, col) not in room_cells:
            corridor_cells.add((row, col))


def _carve_v(col, row_a, row_b, room_cells, corridor_cells):
    for row in range(min(row_a, row_b), max(row_a, row_b) + 1):
        if (row, col) not in room_cells:
            corridor_cells.add((row, col))


def carve_corridors(rooms, mst_edges, room_cells) -> set:
    corridor_cells: set[tuple] = set()
    for (a, b) in mst_edges:
        cx1, cy1 = room_center(rooms[a])
        cx2, cy2 = room_center(rooms[b])
        if random.random() < 0.5:
            _carve_h(cy1, cx1, cx2, room_cells, corridor_cells)
            _carve_v(cx2, cy1, cy2, room_cells, corridor_cells)
        else:
            _carve_v(cx1, cy1, cy2, room_cells, corridor_cells)
            _carve_h(cy2, cx1, cx2, room_cells, corridor_cells)
    return corridor_cells


# ---------------------------------------------------------------------------
# Step 4 — Apply floors to grid
# ---------------------------------------------------------------------------

def apply_floors(grid, room_cells, corridor_cells):
    for (row, col) in room_cells | corridor_cells:
        grid[row][col] = 1


# ---------------------------------------------------------------------------
# Step 5 — Wall placement (8-directional neighbour of any floor → wall)
# ---------------------------------------------------------------------------

def place_walls(grid, width, height):
    floor_cells = {
        (r, c)
        for r in range(height)
        for c in range(width)
        if grid[r][c] == 1
    }
    for row in range(1, height - 1):
        for col in range(1, width - 1):
            if grid[row][col] != 0:
                continue
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    if (row + dr, col + dc) in floor_cells:
                        grid[row][col] = 2
                        break
                else:
                    continue
                break


# ---------------------------------------------------------------------------
# Step 6 — Door placement (choke-point detection)
# ---------------------------------------------------------------------------

def find_doorway_candidates(grid, corridor_cells, room_cells, width, height) -> list:
    """
    A doorway candidate is a corridor cell that:
      - Has the choke-point shape (walls on two opposite sides, floor on the other two)
      - Is adjacent to at least one room cell (i.e. it's a corridor entrance, not mid-corridor)
      - Has no adjacent door already
    """
    candidates = []
    for (row, col) in corridor_cells:
        if grid[row][col] != 1:
            continue

        # Must be adjacent to a room cell in at least one cardinal direction
        near_room = any(
            (row + dr, col + dc) in room_cells
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
        )
        if not near_room:
            continue

        N = grid[row - 1][col] if row > 0          else 0
        S = grid[row + 1][col] if row < height - 1 else 0
        W = grid[row][col - 1] if col > 0          else 0
        E = grid[row][col + 1] if col < width - 1  else 0

        is_choke = (
            (N == 2 and S == 2 and E == 1 and W == 1) or
            (E == 2 and W == 2 and N == 1 and S == 1)
        )
        if not is_choke:
            continue

        # No adjacent door already
        if any(
            grid[row + dr][col + dc] in (3, 4, 5)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            if 0 <= row + dr < height and 0 <= col + dc < width
        ):
            continue

        candidates.append((row, col))
    return candidates


def place_doors(grid, candidates, wood_pct=0.60, iron_pct=0.10):
    random.shuffle(candidates)
    for (row, col) in candidates:
        r = random.random()
        if r < iron_pct:
            grid[row][col] = 4
        elif r < iron_pct + wood_pct:
            grid[row][col] = 3


# ---------------------------------------------------------------------------
# Step 7 — Secret doors
# ---------------------------------------------------------------------------

def place_secret_doors(grid, width, height, n):
    candidates = []
    for row in range(1, height - 1):
        for col in range(1, width - 1):
            if grid[row][col] != 2:
                continue
            floor_neighbours = sum(
                1 for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
                if grid[row + dr][col + dc] == 1
            )
            if floor_neighbours >= 2:
                candidates.append((row, col))

    random.shuffle(candidates)
    for row, col in candidates[:n]:
        grid[row][col] = 5


# ---------------------------------------------------------------------------
# Step 8 — Traps
# ---------------------------------------------------------------------------

def place_traps(grid, corridor_cells, room_cells, width, height, n):
    candidates = []
    for (row, col) in corridor_cells:
        if grid[row][col] != 1:
            continue
        # Not adjacent to a door
        if any(
            grid[row + dr][col + dc] in (3, 4, 5)
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
            if 0 <= row + dr < height and 0 <= col + dc < width
        ):
            continue
        # Not immediately adjacent to a room cell
        if any(
            (row + dr, col + dc) in room_cells
            for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1))
        ):
            continue
        candidates.append((row, col))

    random.shuffle(candidates)
    for row, col in candidates[:n]:
        grid[row][col] = 6


# ---------------------------------------------------------------------------
# Step 9 — Output
# ---------------------------------------------------------------------------

def write_output(grid, path):
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    with open(path, 'w') as f:
        for row in grid:
            f.write(''.join(str(cell) for cell in row) + '\n')


# ---------------------------------------------------------------------------
# PNG export
# ---------------------------------------------------------------------------

def save_png(grid, txt_path, dir_path="./", tile_size=20):
    """Render the generated map to a PNG using MapManager's drawing code."""
    import pygame
    from Core.server import GameServer
    from Core.map_manager import MapManager

    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    width  = cols * tile_size
    height = rows * tile_size

    pygame.init()
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption("Generating preview...")

    server = GameServer()
    mm = MapManager(server=server, dir_path=dir_path, map_data=[row[:] for row in grid])
    mm.tile_size = tile_size
    mm.offset_x  = 0
    mm.offset_y  = 0

    # Replicate the convert() calls from init_pygame (requires display to exist)
    mm.floor_texture_original                  = mm.floor_texture_original.convert()
    mm.wall_texture_original                   = mm.wall_texture_original.convert()
    mm.wooden_door_closed_texture_original     = mm.wooden_door_closed_texture_original.convert_alpha()
    mm.wooden_door_open_texture_original       = mm.wooden_door_open_texture_original.convert_alpha()
    mm.iron_door_closed_texture_original       = mm.iron_door_closed_texture_original.convert_alpha()
    mm.iron_door_open_texture_original         = mm.iron_door_open_texture_original.convert_alpha()
    mm.trap_texture_original                   = mm.trap_texture_original.convert_alpha()
    mm.secret_door_texture_original            = mm.wall_texture_original  # same as wall

    (mm.floor_texture, mm.wall_texture, mm.wooden_door_closed_texture,
     mm.wooden_door_open_texture, mm.iron_door_closed_texture,
     mm.iron_door_open_texture, mm.secret_door_texture,
     mm.trap_texture) = mm.scale_textures(tile_size)

    screen.fill((0, 0, 0))
    mm.draw_map(screen)
    mm.draw_grid(screen)

    png_path = os.path.splitext(txt_path)[0] + ".png"
    pygame.image.save(screen, png_path)
    pygame.quit()
    print(f"  PNG preview  : {png_path}")


# ---------------------------------------------------------------------------
# Step 10 — Stats
# ---------------------------------------------------------------------------

def print_stats(rooms, room_cells, corridor_cells, grid, width, height, output_path):
    floor_total = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 1)
    wall_total  = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 2)
    wood_doors  = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 3)
    iron_doors  = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 4)
    secret      = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 5)
    traps       = sum(1 for r in range(height) for c in range(width) if grid[r][c] == 6)
    print(f"\nGenerated dungeon: {width} x {height} tiles")
    print(f"  Rooms placed : {len(rooms)}")
    print(f"  Floor cells  : {floor_total}  (room: {len(room_cells)}, corridor: {len(corridor_cells)})")
    print(f"  Walls        : {wall_total}")
    print(f"  Doors        : {wood_doors} wooden, {iron_doors} iron")
    print(f"  Secret doors : {secret}")
    print(f"  Traps        : {traps}")
    print(f"  Saved to     : {output_path}")


# ---------------------------------------------------------------------------
# CLI / main
# ---------------------------------------------------------------------------

def _prompt_int(label, default):
    raw = input(f"  {label} [{default}]: ").strip()
    return int(raw) if raw else default


def _prompt_str(label, default):
    raw = input(f"  {label} [{default}]: ").strip()
    return raw if raw else default


def parse_args():
    parser = argparse.ArgumentParser(description="DungeonPy random map generator")
    parser.add_argument('--seed', type=int, default=None,
                        help="Random seed for reproducible output")
    parser.add_argument('--dir', type=str, default='./',
                        help="Base directory for textures (default: ./)")
    parser.add_argument('--no-png', action='store_true',
                        help="Skip PNG preview generation")
    return parser.parse_args()


def main():
    args = parse_args()

    print("=== DungeonPy Map Generator ===")
    width       = _prompt_int("Grid width  (tiles)", 80)
    height      = _prompt_int("Grid height (tiles)", 60)
    num_rooms   = _prompt_int("Number of rooms",     8)
    output_path = _prompt_str("Output file", "Maps/generated_dungeon.txt")

    # Sanity check
    min_room_w, min_room_h = 5, 5
    if width < min_room_w + 4 or height < min_room_h + 4:
        print(f"Error: grid is too small to fit even one room "
              f"(minimum {min_room_w + 4} x {min_room_h + 4}).", file=sys.stderr)
        sys.exit(1)

    if args.seed is not None:
        random.seed(args.seed)
        print(f"  Using seed: {args.seed}")

    # --- Pipeline ---
    grid = [[0] * width for _ in range(height)]

    rooms, room_cells = place_rooms(width, height, num_rooms)
    if not rooms:
        print("Error: no rooms could be placed.", file=sys.stderr)
        sys.exit(1)

    mst_edges      = build_mst(rooms)
    corridor_cells = carve_corridors(rooms, mst_edges, room_cells)

    apply_floors(grid, room_cells, corridor_cells)
    place_walls(grid, width, height)

    candidates = find_doorway_candidates(grid, corridor_cells, room_cells, width, height)
    place_doors(grid, candidates)

    n_secret = random.randint(1, 3)
    n_traps  = random.randint(1, 5)
    place_secret_doors(grid, width, height, n_secret)
    place_traps(grid, corridor_cells, room_cells, width, height, n_traps)

    write_output(grid, output_path)
    print_stats(rooms, room_cells, corridor_cells, grid, width, height, output_path)

    if not args.no_png:
        save_png(grid, output_path, dir_path=args.dir)


if __name__ == '__main__':
    main()
