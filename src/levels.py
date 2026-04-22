"""Level storage, loading, saving for Hexoban.

Hexoban level format (extended XSB for hex grids):

Base characters (original):
  # = wall  @ = player  + = player on target
  $ = box   * = box on target  . = target  (space) = floor
  _ = empty (void)

Extended characters (new in v2):
  a b c d = slab (pressure plate) for laser group 1..4
  A B C D = laser tile (deadly beam) of group 1..4
  e f g h = key of color 1..4 (red/green/blue/yellow)
  E F G H = gate of color 1..4 (blocks until a matching key is collected)

Mechanics:
  - Laser of group G is ON unless >=1 slab of group G is occupied by the
    player or a box. An active laser blocks movement (treated as a wall).
    An inactive laser behaves like a floor.
  - Keys are picked up by the player on entry and added to inventory.
  - Gates act as walls until the player has a matching-color key; entering
    a gate consumes one key of that color and permanently converts the
    gate to floor for the rest of the level (undoable).

Hex grid uses offset coordinates (odd-r offset):
  - Even rows are flush left
  - Odd rows are shifted right by half a hex width
"""
import json
from pathlib import Path
from typing import Optional

LEVELS_DIR = Path("levels")

# ─── Base tile IDs (unchanged for backward compat) ───
EMPTY = 0
WALL = 1
FLOOR = 2
TARGET = 3
BOX = 4
BOX_ON_TARGET = 5
PLAYER = 6
PLAYER_ON_TARGET = 7

# ─── Extended tile IDs (v2) ───
# Encoded as distinct integer IDs so existing `tid == WALL` checks still work.
#   10..13 = slabs (group 0..3)
#   20..23 = lasers (group 0..3)
#   30..33 = keys   (color 0..3)
#   40..43 = gates  (color 0..3)
#   50     = portal-blue  (entry) — step on to teleport to orange, if switch ON
#   60     = portal-orange (destination) — receives teleports only
#   70     = switch — latching toggle; controls whether the portal works
#   80..83 = colored target (color 0..3) — only a matching colored box counts
#   100    = crumble tile — single-use floor; collapses to void after player leaves
#   101    = radioactive tile — deadly floor unless player wears CBRN
#   102    = CBRN item — protective clothing; picked up on entry
SLAB_BASE = 10
LASER_BASE = 20
KEY_BASE = 30
GATE_BASE = 40
PORTAL_IN = 50
PORTAL_OUT = 60
SWITCH = 70
COLORED_TARGET_BASE = 80
CRUMBLE = 100
RADIOACTIVE = 101
CBRN_ITEM = 102
NUM_LASER_GROUPS = 4
NUM_KEY_COLORS = 4
NUM_BOX_COLORS = 4


def slab_id(group: int) -> int:
    return SLAB_BASE + group


def laser_id(group: int) -> int:
    return LASER_BASE + group


def key_id(color: int) -> int:
    return KEY_BASE + color


def gate_id(color: int) -> int:
    return GATE_BASE + color


def colored_target_id(color: int) -> int:
    return COLORED_TARGET_BASE + color


def is_slab(tid: int) -> bool:
    return SLAB_BASE <= tid < SLAB_BASE + NUM_LASER_GROUPS


def is_laser(tid: int) -> bool:
    return LASER_BASE <= tid < LASER_BASE + NUM_LASER_GROUPS


def is_key(tid: int) -> bool:
    return KEY_BASE <= tid < KEY_BASE + NUM_KEY_COLORS


def is_gate(tid: int) -> bool:
    return GATE_BASE <= tid < GATE_BASE + NUM_KEY_COLORS


def is_portal_in(tid: int) -> bool:
    return tid == PORTAL_IN


def is_portal_out(tid: int) -> bool:
    return tid == PORTAL_OUT


def is_switch(tid: int) -> bool:
    return tid == SWITCH


def is_colored_target(tid: int) -> bool:
    return COLORED_TARGET_BASE <= tid < COLORED_TARGET_BASE + NUM_BOX_COLORS


def is_crumble(tid: int) -> bool:
    return tid == CRUMBLE


def is_radioactive(tid: int) -> bool:
    return tid == RADIOACTIVE


def is_cbrn_item(tid: int) -> bool:
    return tid == CBRN_ITEM


def slab_group(tid: int) -> int:
    return tid - SLAB_BASE


def laser_group(tid: int) -> int:
    return tid - LASER_BASE


def key_color(tid: int) -> int:
    return tid - KEY_BASE


def gate_color(tid: int) -> int:
    return tid - GATE_BASE


def target_color(tid: int) -> int:
    """Color of a colored-target tile (0..3)."""
    return tid - COLORED_TARGET_BASE


def is_walkable_base(tid: int) -> bool:
    """True if a tile is inherently floor-like ignoring runtime state."""
    if tid in (FLOOR, TARGET, CRUMBLE, RADIOACTIVE, CBRN_ITEM):
        return True
    return (is_slab(tid) or is_key(tid) or is_portal_in(tid)
            or is_portal_out(tid) or is_switch(tid)
            or is_colored_target(tid))


def is_blocking_base(tid: int) -> bool:
    """True if a tile unconditionally blocks movement (walls & void)."""
    return tid == WALL or tid == EMPTY


# ─── Character <-> tile id mapping ───
# Colored boxes occupy a transient tile-ID range used only during parsing;
# the engine turns them into entries in its `boxes` dict keyed by position
# with color metadata, and the underlying grid cell becomes FLOOR or a
# colored target. These IDs never appear in the final engine grid.
COLORED_BOX_PARSE_BASE = 90          # 90..93  → box of color 0..3 on floor
COLORED_BOX_ON_TARGET_PARSE_BASE = 94  # 94..97 → box of color C on matching target

CHAR_MAP = {
    "#": WALL, " ": FLOOR, "-": FLOOR, ".": TARGET,
    "$": BOX, "*": BOX_ON_TARGET, "@": PLAYER, "+": PLAYER_ON_TARGET,
    "_": EMPTY,
}
# Extended chars
for _g in range(NUM_LASER_GROUPS):
    CHAR_MAP[chr(ord("a") + _g)] = slab_id(_g)
    CHAR_MAP[chr(ord("A") + _g)] = laser_id(_g)
for _c in range(NUM_KEY_COLORS):
    CHAR_MAP[chr(ord("e") + _c)] = key_id(_c)
    CHAR_MAP[chr(ord("E") + _c)] = gate_id(_c)
# Portal: lowercase 'p' = blue (entry); uppercase 'P' = orange (destination)
CHAR_MAP["p"] = PORTAL_IN
CHAR_MAP["P"] = PORTAL_OUT
# Switch: 'w' — toggles the single portal on/off
CHAR_MAP["w"] = SWITCH
# Colored targets: m/n/o/v = target of color 0..3
_TARGET_COLOR_CHARS = ("m", "n", "o", "v")
for _c in range(NUM_BOX_COLORS):
    CHAR_MAP[_TARGET_COLOR_CHARS[_c]] = colored_target_id(_c)
# Crumble floor: 'x' (single-use; collapses to void after the player leaves).
CHAR_MAP["x"] = CRUMBLE
# Radioactive floor: 'R' (deadly unless player wears CBRN protective clothing).
CHAR_MAP["R"] = RADIOACTIVE
# CBRN protective clothing item: 'S' (suit). Picked up on entry;
# enables traversal of radioactive tiles for the rest of the level.
CHAR_MAP["S"] = CBRN_ITEM
# Colored boxes on floor: digits 1..4 → sentinel parse IDs
# Colored boxes on matching colored target: uppercase M/N/O/V → sentinel parse IDs
_COLORED_BOX_CHARS = ("1", "2", "3", "4")
_COLORED_BOX_ON_TARGET_CHARS = ("M", "N", "O", "V")
for _c in range(NUM_BOX_COLORS):
    CHAR_MAP[_COLORED_BOX_CHARS[_c]] = COLORED_BOX_PARSE_BASE + _c
    CHAR_MAP[_COLORED_BOX_ON_TARGET_CHARS[_c]] = COLORED_BOX_ON_TARGET_PARSE_BASE + _c


def is_colored_box_parse(tid: int) -> bool:
    return COLORED_BOX_PARSE_BASE <= tid < COLORED_BOX_PARSE_BASE + NUM_BOX_COLORS


def is_colored_box_on_target_parse(tid: int) -> bool:
    return (COLORED_BOX_ON_TARGET_PARSE_BASE
            <= tid < COLORED_BOX_ON_TARGET_PARSE_BASE + NUM_BOX_COLORS)


def colored_box_parse_color(tid: int) -> int:
    if is_colored_box_parse(tid):
        return tid - COLORED_BOX_PARSE_BASE
    return tid - COLORED_BOX_ON_TARGET_PARSE_BASE

ID_TO_CHAR = {v: k for k, v in CHAR_MAP.items()}
ID_TO_CHAR[FLOOR] = " "
ID_TO_CHAR[EMPTY] = "_"

HEX_DIRECTIONS = ["TOP_LEFT", "TOP_RIGHT", "LEFT", "RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT"]

EVEN_ROW_DIRS = {
    "TOP_LEFT":     (-1, -1),
    "TOP_RIGHT":    (-1,  0),
    "LEFT":         ( 0, -1),
    "RIGHT":        ( 0,  1),
    "BOTTOM_LEFT":  ( 1, -1),
    "BOTTOM_RIGHT": ( 1,  0),
}
ODD_ROW_DIRS = {
    "TOP_LEFT":     (-1,  0),
    "TOP_RIGHT":    (-1,  1),
    "LEFT":         ( 0, -1),
    "RIGHT":        ( 0,  1),
    "BOTTOM_LEFT":  ( 1,  0),
    "BOTTOM_RIGHT": ( 1,  1),
}


def hex_neighbor(r: int, c: int, direction: str) -> tuple:
    if r % 2 == 0:
        dr, dc = EVEN_ROW_DIRS[direction]
    else:
        dr, dc = ODD_ROW_DIRS[direction]
    return r + dr, c + dc


def hex_neighbors(r: int, c: int) -> dict:
    dirs = EVEN_ROW_DIRS if r % 2 == 0 else ODD_ROW_DIRS
    return {d: (r + dr, c + dc) for d, (dr, dc) in dirs.items()}


# ─── Built-in levels ───
BUILTIN_LEVELS = [
    # ═══ TUTORIAL ═══
    {"name": "1. First Push", "data": [
        "# # # # #",
        " # # # #",
        "# @ $ . #",
        " # # # #",
        "# # # # #",
    ]},
    {"name": "2. Push Left", "data": [
        "# # # # #",
        " # # # #",
        "# . $ @ #",
        " # # # #",
        "# # # # #",
    ]},
    {"name": "3. Short Walk", "data": [
        "# # # # # # #",
        " #         #",
        "#   @ $   . #",
        " #         #",
        "# # # # # # #",
    ]},
    {"name": "4. Hex Diagonal", "data": [
        "# # # # #",
        " # # @ #",
        "# # $ # #",
        " # . # #",
        "# # # # #",
    ]},
    {"name": "5. Navigate", "data": [
        "# # # # # #",
        " #       #",
        "#   $ #   #",
        " # @ . # #",
        "# # # # # #",
    ]},
    # ═══ EASY ═══
    {"name": "6. Mirror", "data": [
        "# # # # # # #",
        " #         #",
        "# . $ @ $ . #",
        " #         #",
        "# # # # # # #",
    ]},
    {"name": "7. Step Down", "data": [
        "# # # # # # #",
        " #         #",
        "#   @ $ . # #",
        " #   $ . # #",
        "# # # # # # #",
    ]},
    {"name": "8. Hex Angles", "data": [
        "# # # # # # # # #",
        " #             #",
        "#     . $ @ $   #",
        " #         .   #",
        "# # # # # # # # #",
    ]},
    {"name": "9. Three Rooms", "data": [
        "# # # # # # # #",
        " #           #",
        "# . $ @ $ .   #",
        " #   $       #",
        "#   .       # #",
        " # # # # # # #",
    ]},
    {"name": "10. Hex Pair", "data": [
        "# # # # # # #",
        " #         #",
        "# . $ @ $   #",
        " # .       #",
        "# # # # # # #",
    ]},
    # ═══ MEDIUM ═══
    {"name": "11. Three Hex", "data": [
        "# # # # # # # # #",
        " #             #",
        "# . $ @ $ . $ . #",
        " #             #",
        "# # # # # # # # #",
    ]},
    {"name": "12. Hex Cross", "data": [
        "# # # # # # # #",
        " #     .     #",
        "#   $   . $   #",
        " #   @ $     #",
        "#       .     #",
        " # # # # # # #",
    ]},
    {"name": "13. Hex Network", "data": [
        "# # # # # # # # #",
        " #   .   .     #",
        "#   $     $     #",
        " # @           #",
        "#   $     $     #",
        " #   .   .     #",
        "# # # # # # # # #",
    ]},
    {"name": "14. Gauntlet", "data": [
        "# # # # # # # # # #",
        " #   .   .       #",
        "#   $     $       #",
        " # @             #",
        "#   $     $       #",
        " #   .   .       #",
        "# # # # # # # # # #",
    ]},
    {"name": "15. Hex Rooms", "data": [
        "# # # # # # # # #",
        " #           . #",
        "#   . $   $     #",
        " #   @ $ .     #",
        "# # # # # # # # #",
    ]},
    # ═══ HARD ═══
    {"name": "16. Triple Path", "data": [
        "# # # # # # # # # #",
        " #               #",
        "# . $ . $ . $ @   #",
        " #               #",
        "# # # # # # # # # #",
    ]},
    {"name": "17. Wide Open", "data": [
        "# # # # # # # # # #",
        " #               #",
        "#   . $   $   .   #",
        " #   # # @ # #   #",
        "#     $       .   #",
        " # # # # # # # # #",
    ]},
    {"name": "18. Hex Challenge", "data": [
        "# # # # # # # # # # #",
        " #                 #",
        "# . $   # # # $ .   #",
        " #       @   $     #",
        "#   .     # #     # #",
        " # # # # # # # # # #",
    ]},
    {"name": "19. Hex Fortress", "data": [
        "# # # # # # # # # # # # #",
        " # .                 . # #",
        "#   $   # # # # #   $   #",
        " #         $ @           #",
        "#   $   # # # # #   .   #",
        " # .                   # #",
        "# # # # # # # # # # # # #",
    ]},
    {"name": "20. Open Four", "data": [
        "# # # # # # # # # # # #",
        " # .   $         . $   #",
        "#       # # # #         #",
        " #         @           #",
        "#       # # # #         #",
        " # .   $         . $   #",
        "# # # # # # # # # # # #",
    ]},
    # ═══ EXTREME ═══
    {"name": "21. Hex Depot", "data": [
        "# # # # # # # # # #",
        " #               #",
        "# . . . $ $ $ @   #",
        " #     $         #",
        "#     .         # #",
        " # # # # # # # # #",
    ]},
    {"name": "22. Hex Depot II", "data": [
        "# # # # # # # # # # #",
        " # .             . #",
        "#   $ # # # # # $   #",
        " #       $ @       #",
        "#   $ # # # # # .   #",
        " # .               #",
        "# # # # # # # # # # #",
    ]},
    {"name": "23. Quad Push", "data": [
        "# # # # # # # # # # #",
        " # .   $   . $     #",
        "#         @         #",
        " # .   $   . $     #",
        "# # # # # # # # # # #",
    ]},
    {"name": "24. Hex Extreme", "data": [
        "# # # # # # # # # #",
        " #               #",
        "# . . . $ $ $ @   #",
        " #     $         #",
        "#     .         # #",
        " # # # # # # # # #",
    ]},
    {"name": "25. Grand Hex", "data": [
        "# # # # # # # # # # # # #",
        " # .                 . #",
        "#   $   # # # # #   $   #",
        "#           $ @           #",
        " # $   # # # # #   .   #",
        " # .                   #",
        "# # # # # # # # # # # # #",
    ]},
    # ═══ DEMO ═══
    # Showcases: slab 'a' disarms laser beam 'A A A', then key 'e'
    # opens gate 'E' so the player can push a box to the target.
    {"name": "26. Laser & Key Demo", "data": [
        "# # # # # # # # # # #",
        " #                 #",
        "# @   a   A A A     #",
        " #                 #",
        "#       $ e E . #   #",
        " #                 #",
        "# # # # # # # # # # #",
    ]},
    # Portal demo: step on switch 'w' to enable portal pair 0; then walking
    # onto portal-blue 'p' teleports the player to portal-orange 'P'.
    {"name": "27. Portal Switch Demo", "data": [
        "# # # # # # # # # #",
        " #               #",
        "# @ w             #",
        " #               #",
        "# # # # # p # # # #",
        " #               #",
        "# P   $ .         #",
        " #               #",
        "# # # # # # # # # #",
    ]},
    # Colored-box demo: box '1' must land on target 'm' (both color 0),
    # box '2' on 'n' (color 1). Regular '$' on '.' works as before.
    {"name": "28. Colored Boxes Demo", "data": [
        "# # # # # # # # #",
        " #             #",
        "# @ 1   m       #",
        " #             #",
        "#   2   n       #",
        " #             #",
        "#   $   .       #",
        " #             #",
        "# # # # # # # # #",
    ]},
    # Hazard demo: 'x' crumble tiles collapse after the player leaves,
    # 'R' radioactive tiles need 'S' (CBRN suit) to cross, then the
    # classic box-push completes the level. The crumble corridor
    # forces a one-way route.
    {"name": "29. Hazard Floor Demo", "data": [
        "# # # # # # # # # # #",
        " #                 #",
        "# @ S x x R   $ .   #",
        " #                 #",
        "# # # # # # # # # # #",
    ]},
]


def parse_level(lines: list) -> tuple:
    """Parse hex level lines -> (grid, player_row, player_col)."""
    grid = []
    pr, pc = 0, 0
    max_cols = 0

    parsed_rows = []
    for r, line in enumerate(lines):
        if r % 2 == 1 and line.startswith(' '):
            content = line[1:]
        else:
            content = line

        chars = []
        for i in range(0, len(content), 2):
            if i < len(content):
                chars.append(content[i])

        row = []
        for c, ch in enumerate(chars):
            tid = CHAR_MAP.get(ch, EMPTY)
            if tid == PLAYER:
                pr, pc = r, c
                tid = FLOOR
            elif tid == PLAYER_ON_TARGET:
                pr, pc = r, c
                tid = TARGET
            row.append(tid)
        parsed_rows.append(row)
        if len(row) > max_cols:
            max_cols = len(row)

    for row in parsed_rows:
        while len(row) < max_cols:
            row.append(EMPTY)

    return parsed_rows, pr, pc


def grid_to_xsb(grid: list, player_r: int, player_c: int,
                 boxes) -> list:
    """Convert hex grid back to spaced text lines.

    `boxes` can be either:
      - a set of (r, c) tuples — all boxes are uncolored (classic behavior)
      - a dict {(r, c): color} where color == -1 means uncolored

    For colored boxes we use chars '1'..'4' on floor and 'M' 'N' 'O' 'V' on a
    *matching* colored target. On a mismatched colored target (a situation
    that cannot occur in a winning state, but may occur mid-save) we fall
    back to just the box char and lose the target information — callers
    should avoid saving partial play states.
    """
    # Normalize to dict: position -> color (or -1)
    if isinstance(boxes, dict):
        box_colors = boxes
    else:
        box_colors = {pos: -1 for pos in boxes}

    lines = []
    for r, row in enumerate(grid):
        prefix = " " if r % 2 == 1 else ""
        chars = []
        for c, tid in enumerate(row):
            pos = (r, c)
            if pos == (player_r, player_c):
                # Player glyph: overlays whatever is underneath
                if tid == TARGET:
                    chars.append("+")
                elif is_colored_target(tid):
                    # Player-on-colored-target: save as '+' (loses target color)
                    chars.append("+")
                else:
                    chars.append("@")
            elif pos in box_colors:
                color = box_colors[pos]
                if color < 0:
                    # Uncolored box
                    chars.append("*" if tid == TARGET else "$")
                else:
                    # Colored box
                    if is_colored_target(tid) and target_color(tid) == color:
                        chars.append(_COLORED_BOX_ON_TARGET_CHARS[color])
                    else:
                        chars.append(_COLORED_BOX_CHARS[color])
            else:
                ch = ID_TO_CHAR.get(tid, "_")
                chars.append(ch)
        while chars and chars[-1] == "_":
            chars.pop()
        if not chars:
            chars = ["_"]
        lines.append(prefix + " ".join(chars))
    return lines


def load_level_file(path: str) -> Optional[dict]:
    p = Path(path)
    if not p.exists():
        return None
    if p.suffix == ".json":
        with open(p) as f:
            return json.load(f)
    with open(p) as f:
        lines = [l.rstrip("\n") for l in f.readlines()]
    return {"name": p.stem, "data": lines}


def save_level_file(path: str, name: str, lines: list):
    LEVELS_DIR.mkdir(exist_ok=True)
    p = Path(path)
    if p.exists():
        import stat
        try:
            p.chmod(p.stat().st_mode | stat.S_IWUSR | stat.S_IWGRP)
        except OSError:
            base = p.stem
            for i in range(1, 100):
                alt = p.parent / f"{base}_{i}.json"
                if not alt.exists():
                    p = alt
                    break
    try:
        with open(p, "w") as f:
            json.dump({"name": name, "data": lines}, f, indent=2)
    except PermissionError:
        import time
        alt = p.parent / f"{p.stem}_{int(time.time())}.json"
        with open(alt, "w") as f:
            json.dump({"name": name, "data": lines}, f, indent=2)


def list_saved_levels() -> list:
    LEVELS_DIR.mkdir(exist_ok=True)
    return sorted(LEVELS_DIR.glob("*.json"))


def get_builtin_level(index: int) -> dict:
    return BUILTIN_LEVELS[index % len(BUILTIN_LEVELS)]
