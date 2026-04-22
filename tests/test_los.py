"""
Tests for Core.los.compute_los — line-of-sight computation.

Grid convention: map_grid[row][col], pos is (col, row).
Tile codes: 0=void (opaque), 1=floor (transparent), 2=wall (opaque),
            3=wooden door, 4=iron door, 5=secret door.
"""

from Core.los import compute_los


# ---------------------------------------------------------------------------
# Grids used across multiple tests
# ---------------------------------------------------------------------------

# 5×5 walled room: walls on the border, floor inside.
ROOM = [
    [2, 2, 2, 2, 2],
    [2, 1, 1, 1, 2],
    [2, 1, 1, 1, 2],
    [2, 1, 1, 1, 2],
    [2, 2, 2, 2, 2],
]

# Single-row corridor with a wall in the middle.
# col:  0  1  2  3  4
CORRIDOR_WALL = [[1, 1, 2, 1, 1]]

# Single-row corridor with a wooden door in the middle.
CORRIDOR_DOOR = [[1, 1, 3, 1, 1]]

# Single-row corridor with an iron door in the middle.
CORRIDOR_IRON = [[1, 1, 4, 1, 1]]

# Single-row corridor with a secret door in the middle.
CORRIDOR_SECRET = [[1, 1, 5, 1, 1]]

# Single-row corridor with a void tile (tile 0) in the middle.
CORRIDOR_VOID = [[1, 1, 0, 1, 1]]


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_empty_grid_returns_empty():
    assert compute_los([], (0, 0), radius=5) == set()


def test_radius_zero_returns_empty():
    assert compute_los(ROOM, (2, 2), radius=0) == set()


def test_radius_negative_returns_empty():
    assert compute_los(ROOM, (2, 2), radius=-1) == set()


def test_origin_always_visible():
    result = compute_los(ROOM, (2, 2), radius=5)
    assert (2, 2) in result


def test_out_of_bounds_tiles_not_returned():
    result = compute_los(ROOM, (2, 2), radius=20)
    rows = len(ROOM)
    cols = len(ROOM[0])
    for col, row in result:
        assert 0 <= row < rows
        assert 0 <= col < cols


# ---------------------------------------------------------------------------
# Basic visibility
# ---------------------------------------------------------------------------


def test_all_floor_tiles_visible_in_small_room():
    result = compute_los(ROOM, (2, 2), radius=5)
    for col in range(1, 4):
        for row in range(1, 4):
            assert (col, row) in result, f"floor tile ({col}, {row}) should be visible"


def test_wall_tile_itself_is_visible():
    # The wall at the edge of the room should be visible from the centre.
    result = compute_los(ROOM, (2, 2), radius=5)
    assert (0, 2) in result  # left wall, same row


def test_radius_limits_range():
    # From (1,1) with radius=1, only tiles at Chebyshev distance ≤ 1 may appear.
    result = compute_los(ROOM, (1, 1), radius=1)
    for col, row in result:
        assert abs(col - 1) <= 1 and abs(row - 1) <= 1


# ---------------------------------------------------------------------------
# Wall blocking
# ---------------------------------------------------------------------------


def test_wall_blocks_sight_beyond_it():
    result = compute_los(CORRIDOR_WALL, (0, 0), radius=10)
    assert (2, 0) in result  # wall tile itself is visible
    assert (3, 0) not in result  # blocked beyond the wall
    assert (4, 0) not in result


def test_void_tile_blocks_sight_beyond_it():
    result = compute_los(CORRIDOR_VOID, (0, 0), radius=10)
    assert (2, 0) in result  # void tile itself is visible (you see the edge)
    assert (3, 0) not in result


# ---------------------------------------------------------------------------
# Doors
# ---------------------------------------------------------------------------


def test_wooden_door_closed_by_default_blocks():
    # No door_states passed → defaults to closed.
    result = compute_los(CORRIDOR_DOOR, (0, 0), radius=10)
    assert (3, 0) not in result


def test_wooden_door_closed_explicitly_blocks():
    door_states = {(0, 2): "closed"}
    result = compute_los(CORRIDOR_DOOR, (0, 0), radius=10, door_states=door_states)
    assert (3, 0) not in result


def test_wooden_door_open_transparent():
    door_states = {(0, 2): "open"}
    result = compute_los(CORRIDOR_DOOR, (0, 0), radius=10, door_states=door_states)
    assert (3, 0) in result
    assert (4, 0) in result


def test_iron_door_closed_blocks():
    result = compute_los(CORRIDOR_IRON, (0, 0), radius=10)
    assert (3, 0) not in result


def test_iron_door_open_transparent():
    iron_states = {(0, 2): "open"}
    result = compute_los(CORRIDOR_IRON, (0, 0), radius=10, iron_door_states=iron_states)
    assert (3, 0) in result


def test_secret_door_closed_blocks():
    result = compute_los(CORRIDOR_SECRET, (0, 0), radius=10)
    assert (3, 0) not in result


def test_secret_door_open_transparent():
    secret_states = {(0, 2): "open"}
    result = compute_los(
        CORRIDOR_SECRET, (0, 0), radius=10, secret_door_states=secret_states
    )
    assert (3, 0) in result


# ---------------------------------------------------------------------------
# Corner blocking (LOS travels in straight lines)
# ---------------------------------------------------------------------------


def test_cannot_see_around_a_corner():
    # L-shaped map: observer at (0,0), wall at (1,0), open floor at (1,1).
    # (1,1) is around the corner — should NOT be visible from (0,0).
    grid = [
        [1, 2, 1],  # row 0: floor, wall, floor
        [1, 1, 1],  # row 1: floor
    ]
    result = compute_los(grid, (0, 0), radius=5)
    assert (2, 0) not in result  # blocked by wall at (1,0)
