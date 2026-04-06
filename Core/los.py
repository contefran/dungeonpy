"""
los.py — Line-of-sight computation for DungeonPy.

compute_los(map_grid, pos, radius, door_states, iron_door_states, secret_door_states)
    → frozenset of (col, row) tuples the origin can see.

Algorithm: for every tile within the circular radius, walk a Bresenham line
from the origin and mark it visible only if the path is unobstructed.
At radius ≤ 20 this is fast enough to run every frame in pure Python.

Tile opacity rules  (must match draw_map numbering):
  0  void/outside — opaque  (black empty space outside the dungeon)
  1  floor        — transparent
  2  wall         — opaque
  3  wooden door  — opaque when closed, transparent when open
  4  iron door    — opaque when closed, transparent when open
  5  secret door  — opaque when closed, transparent when open (fog-gated per player)
  6  trap         — transparent (floor-like)
"""


def compute_los(map_grid, pos, radius,
                door_states=None,
                iron_door_states=None,
                secret_door_states=None):
    """
    Return a set of (col, row) tiles visible from *pos* within *radius*.

    Parameters
    ----------
    map_grid : list[list[int]]
        2-D tile grid, row-major (map_grid[row][col]).
    pos : (int, int)
        (col, row) of the viewer.
    radius : int
        Maximum sight distance in tiles.
    door_states / iron_door_states / secret_door_states : dict | None
        {(row, col): "open"|"closed"} — current door states.
    """
    if not map_grid or radius <= 0:
        return set()

    n_rows = len(map_grid)
    n_cols = len(map_grid[0]) if n_rows else 0
    ox, oy = pos          # origin col, row
    ds  = door_states        or {}
    ids = iron_door_states   or {}
    sds = secret_door_states or {}

    def is_opaque(c, r):
        if not (0 <= r < n_rows and 0 <= c < n_cols):
            return True   # out of bounds treated as solid
        t = map_grid[r][c]
        if t == 0:        return True    # void/outside — opaque
        if t in (1, 6):   return False   # floor, trap — transparent
        if t == 2:        return True    # wall — opaque
        if t == 3:        return ds.get((r, c), "closed") != "open"
        if t == 4:        return ids.get((r, c), "closed") != "open"
        if t == 5:        return sds.get((r, c), "closed") != "open"
        return False

    visible = set()
    r2 = radius * radius

    for dc in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            if dc * dc + dr * dr > r2:
                continue
            tc, tr = ox + dc, oy + dr
            if not (0 <= tr < n_rows and 0 <= tc < n_cols):
                continue
            if _clear_line(ox, oy, tc, tr, is_opaque):
                visible.add((tc, tr))

    return visible


def _clear_line(x0, y0, x1, y1, is_opaque):
    """
    Bresenham line walk from (x0,y0) to (x1,y1).
    Returns True if the destination is reachable without hitting an opaque tile.
    The origin tile is never tested; the destination tile IS tested (a wall tile
    is visible — you can see the wall — but blocks further sight).
    """
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx = 1 if x1 > x0 else -1
    sy = 1 if y1 > y0 else -1
    err = dx - dy
    cx, cy = x0, y0

    while True:
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            cx += sx
        if e2 < dx:
            err += dx
            cy += sy
        if cx == x1 and cy == y1:
            return True          # reached destination — always add it (see the wall)
        if is_opaque(cx, cy):
            return False         # path blocked before reaching destination
