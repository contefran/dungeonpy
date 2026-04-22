"""
los.py — Line-of-sight computation for DungeonPy.

compute_los(map_grid, pos, radius, door_states, iron_door_states, secret_door_states)
    → set of (col, row) tuples the origin can see.

Algorithm:
  Pass 1 — standard Bresenham LOS for every tile within the circular radius.
  Pass 2 — reveal opaque boundary tiles (walls, closed doors) that have at
            least one visible transparent (floor/trap) neighbour.  This fixes
            Bresenham corner-clipping that can hide nearby room walls, and also
            extends wall visibility up to WALL_BONUS tiles beyond the radius so
            that room boundaries never disappear just past the sight circle.
            Because pass 2 only ever adds opaque tiles it cannot cause
            see-through artefacts.

Tile opacity rules  (must match draw_map numbering):
  0  void/outside — opaque
  1  floor        — transparent
  2  wall         — opaque
  3  wooden door  — opaque when closed, transparent when open
  4  iron door    — opaque when closed, transparent when open
  5  secret door  — opaque when closed, transparent when open
  6  trap         — transparent (floor-like)
"""

WALL_BONUS = 4  # extra tiles of radius granted to opaque boundary tiles


def compute_los(
    map_grid,
    pos,
    radius,
    door_states=None,
    iron_door_states=None,
    secret_door_states=None,
):
    """
    Return a set of (col, row) tiles visible from *pos* within *radius*.

    Parameters
    ----------
    map_grid : list[list[int]]
        2-D tile grid, row-major (map_grid[row][col]).
    pos : (int, int)
        (col, row) of the viewer.
    radius : int
        Maximum sight distance in tiles (floor tiles beyond this are hidden).
    door_states / iron_door_states / secret_door_states : dict | None
        {(row, col): "open"|"closed"} — current door states.
    """
    if not map_grid or radius <= 0:
        return set()

    n_rows = len(map_grid)
    n_cols = len(map_grid[0]) if n_rows else 0
    ox, oy = pos
    ds = door_states or {}
    ids = iron_door_states or {}
    sds = secret_door_states or {}

    def is_opaque(c, r):
        if not (0 <= r < n_rows and 0 <= c < n_cols):
            return True
        t = map_grid[r][c]
        if t == 0:
            return True
        if t in (1, 6):
            return False
        if t == 2:
            return True
        if t == 3:
            return ds.get((r, c), "closed") != "open"
        if t == 4:
            return ids.get((r, c), "closed") != "open"
        if t == 5:
            return sds.get((r, c), "closed") != "open"
        return False

    # ------------------------------------------------------------------
    # Pass 1: standard Bresenham LOS within normal radius
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Pass 2: clipping fix — reveal walls/closed-doors within the normal
    # radius whose Bresenham ray was blocked by an adjacent void tile.
    # A wall is revealed if any cardinal floor neighbour is already visible.
    # (Safe: only adds opaque tiles, so no see-through is possible.)
    # ------------------------------------------------------------------
    for dc in range(-radius, radius + 1):
        for dr in range(-radius, radius + 1):
            if dc * dc + dr * dr > r2:
                continue
            tc, tr = ox + dc, oy + dr
            if (tc, tr) in visible:
                continue
            if not (0 <= tr < n_rows and 0 <= tc < n_cols):
                continue
            tile_type = map_grid[tr][tc]
            if tile_type not in (2, 3, 4, 5):
                continue
            if not is_opaque(tc, tr):
                continue  # open door
            for nc, nr in ((tc + 1, tr), (tc - 1, tr), (tc, tr + 1), (tc, tr - 1)):
                if (nc, nr) in visible and not is_opaque(nc, nr):
                    visible.add((tc, tr))
                    break

    # ------------------------------------------------------------------
    # Pass 3: wall-radius bonus — walls/closed-doors beyond the normal
    # radius (up to +WALL_BONUS) that have a clear line of sight.
    # ------------------------------------------------------------------
    r2_wall = (radius + WALL_BONUS) * (radius + WALL_BONUS)

    for dc in range(-(radius + WALL_BONUS), (radius + WALL_BONUS) + 1):
        for dr in range(-(radius + WALL_BONUS), (radius + WALL_BONUS) + 1):
            dist2 = dc * dc + dr * dr
            if dist2 <= r2 or dist2 > r2_wall:
                continue
            tc, tr = ox + dc, oy + dr
            if (tc, tr) in visible:
                continue
            if not (0 <= tr < n_rows and 0 <= tc < n_cols):
                continue
            tile_type = map_grid[tr][tc]
            if tile_type not in (2, 3, 4, 5):
                continue
            if not is_opaque(tc, tr):
                continue  # open door
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
            return True  # reached destination — always visible
        if is_opaque(cx, cy):
            return False  # path blocked
