"""Hexoban (Hexagonal Sokoban) — Arcade 3.x GUI.

Hex grid rendering with pointy-top hexagons, offset coordinates (odd-r).
6 movement directions mapped to numpad: 7=TL, 9=TR, 4=L, 6=R, 1=BL, 3=BR.
"""
from __future__ import annotations

import copy
import math
import time
import threading
from pathlib import Path
from typing import Optional

import arcade
from arcade import XYWH

from src.config_loader import load_config
from src.engine import HexobanEngine, WALL, FLOOR, TARGET, BOX, BOX_ON_TARGET
from src.levels import (
    BUILTIN_LEVELS, get_builtin_level,
    list_saved_levels, load_level_file, save_level_file,
    grid_to_xsb, EMPTY, hex_neighbors,
    is_slab, is_laser, is_key, is_gate,
    is_portal_in, is_portal_out, is_switch, is_colored_target,
    is_crumble, is_radioactive, is_cbrn_item,
    slab_group, laser_group, key_color, gate_color, target_color,
    slab_id, laser_id, key_id, gate_id, colored_target_id,
    PORTAL_IN, PORTAL_OUT, SWITCH,
    CRUMBLE, RADIOACTIVE, CBRN_ITEM,
    NUM_LASER_GROUPS, NUM_KEY_COLORS, NUM_BOX_COLORS,
)
from src.texture_gen import generate_all as gen_textures
from src.solutions import (
    log, load_solution, save_solution, list_solutions,
    get_best_moves, get_solution_moves,
)

# ───────────────────────────────────────────────────────────────────
# Colors
# ───────────────────────────────────────────────────────────────────
C_BG = (24, 24, 32)
C_TITLE = (255, 215, 0)
C_MENU = (150, 150, 165)
C_MENU_SEL = (255, 255, 255)
C_SEL_BAR = (55, 50, 85)
C_HUD = (220, 220, 220)
C_HUD_BAR = (18, 18, 28)
C_OVERLAY = (0, 0, 0, 180)
C_BTN = (50, 50, 70)
C_BTN_HOVER = (75, 70, 105)
C_BTN_BORDER = (100, 95, 140)
C_SUCCESS = (80, 255, 80)
C_WARN = (255, 200, 50)
C_ERR = (255, 80, 80)
C_WALL = (100, 80, 60)
C_FLOOR = (200, 190, 170)
C_BOX = (180, 130, 50)
C_BOX_OUTLINE = (140, 100, 30)
C_TARGET = (220, 60, 60)
C_PLAYER = (50, 100, 200)
C_PLAYER_OUTLINE = (30, 70, 160)
C_BOX_OK = (100, 180, 80)
C_BOX_OK_OUTLINE = (60, 140, 50)
C_CURSOR = (255, 255, 0, 140)
C_HINT = (90, 90, 105)
C_HEX_OUTLINE = (60, 55, 45)
C_VOID = C_BG

MENU_ITEMS = ["New Game", "Load Game", "Level Editor", "Resolver", "Replay", "Optimize", "Credits"]
HUD_H = 48
HINT_H = 36

# ───────────────────────────────────────────────────────────────────
# Hex geometry helpers (pointy-top hexagons)
# ───────────────────────────────────────────────────────────────────

def hex_size_from_tile(tile_size: float) -> float:
    """Return hex radius (center to vertex) from desired tile size."""
    return tile_size / 2.0


def hex_center(r: int, c: int, hex_s: float) -> tuple[float, float]:
    """Pixel center of hex at grid (r, c) using odd-r offset, pointy-top.

    Pointy-top hex:
      width = sqrt(3) * size
      height = 2 * size
      Row spacing: 1.5 * size
      Col spacing: sqrt(3) * size
      Odd rows shifted right by sqrt(3)/2 * size
    """
    w = math.sqrt(3) * hex_s
    x = c * w + (w / 2 if r % 2 == 1 else 0)
    y = r * 1.5 * hex_s
    return x, y


def hex_corners(cx: float, cy: float, s: float) -> list[tuple[float, float]]:
    """Return 6 corners of a pointy-top hexagon centered at (cx, cy)."""
    corners = []
    for i in range(6):
        angle = math.radians(60 * i - 30)  # pointy-top starts at -30°
        corners.append((cx + s * math.cos(angle), cy + s * math.sin(angle)))
    return corners


def _draw_hex_filled(cx: float, cy: float, s: float, color):
    """Draw a filled hexagon."""
    pts = hex_corners(cx, cy, s)
    arcade.draw_polygon_filled(pts, color)


def _draw_hex_outline(cx: float, cy: float, s: float, color, lw=1):
    """Draw a hexagon outline."""
    pts = hex_corners(cx, cy, s)
    arcade.draw_polygon_outline(pts, color, lw)


# ───────────────────────────────────────────────────────────────────
# Palettes for new tile types
# ───────────────────────────────────────────────────────────────────
# Slab/laser groups use one color each; slab is a muted version of the
# laser color. 4 groups: cyan, magenta, yellow, orange.
LASER_GROUP_COLORS = [
    (80, 220, 255),   # group 0 — cyan
    (220, 80, 220),   # group 1 — magenta
    (230, 230, 60),   # group 2 — yellow
    (255, 140, 40),   # group 3 — orange
]
SLAB_GROUP_COLORS = [
    (40, 110, 130),   # dimmer versions
    (110, 40, 110),
    (120, 120, 35),
    (130, 70, 25),
]

# Key/gate colors: red, green, blue, yellow (distinct from laser palette)
KEY_COLORS = [
    (230, 60, 60),    # red
    (60, 200, 90),    # green
    (70, 120, 230),   # blue
    (230, 200, 60),   # yellow
]
GATE_COLORS = [
    (180, 40, 40),    # darker variants
    (40, 150, 60),
    (50, 90, 180),
    (180, 150, 40),
]

# Portal colors — blue entry, orange destination. Fixed per spec.
C_PORTAL_IN = (70, 140, 255)     # saturated blue
C_PORTAL_IN_DIM = (40, 80, 140)  # switch-off variant
C_PORTAL_OUT = (255, 140, 40)    # saturated orange
# Switch: green when ON, dim gray when OFF
C_SWITCH_ON = (80, 230, 120)
C_SWITCH_OFF = (100, 100, 110)

# Box / colored-target palette — distinct from keys/gates so puzzles
# using both systems don't blur visually. 4 colors: red, cyan, lime, purple.
BOX_COLOR_PALETTE = [
    (220, 70, 70),    # red
    (70, 200, 220),   # cyan
    (130, 220, 70),   # lime
    (200, 100, 220),  # purple
]
TARGET_COLOR_PALETTE = [
    (170, 40, 40),    # darker variants for the target disc outline
    (40, 150, 170),
    (90, 170, 40),
    (150, 60, 170),
]


# ───────────────────────────────────────────────────────────────────
# Drawing helpers
# ───────────────────────────────────────────────────────────────────

def _draw_slab_tile(cx: float, cy: float, s: float, group: int, pressed: bool):
    """Pressure plate: hex with a ring in the group color. Pressed = brighter."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = LASER_GROUP_COLORS[group] if pressed else SLAB_GROUP_COLORS[group]
    arcade.draw_circle_outline(cx, cy, s * 0.55, col, 3 if pressed else 2)
    arcade.draw_circle_outline(cx, cy, s * 0.35, col, 1)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_laser_tile(cx: float, cy: float, s: float, group: int, active: bool):
    """Laser beam cell. When active: bright filled hex with crosshatched beam
    glyph. When inactive: dim outline only (acts as floor visually)."""
    if active:
        # Dim floor backdrop
        _draw_hex_filled(cx, cy, s, C_FLOOR)
        col = LASER_GROUP_COLORS[group]
        # Strong bar across the hex as the "beam"
        arcade.draw_line(cx - s * 0.9, cy, cx + s * 0.9, cy, col, 4)
        # Inner glow
        arcade.draw_line(cx - s * 0.9, cy + 3, cx + s * 0.9, cy + 3,
                         (*col, 120) if len(col) == 3 else col, 1)
        arcade.draw_line(cx - s * 0.9, cy - 3, cx + s * 0.9, cy - 3,
                         (*col, 120) if len(col) == 3 else col, 1)
        _draw_hex_outline(cx, cy, s, col, 2)
    else:
        # Inactive laser — faint outline only
        _draw_hex_filled(cx, cy, s, C_FLOOR)
        col = SLAB_GROUP_COLORS[group]
        arcade.draw_line(cx - s * 0.6, cy, cx + s * 0.6, cy, col, 1)
        _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_key_tile(cx: float, cy: float, s: float, color: int):
    """Key on the floor — small key-shaped glyph in the color."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = KEY_COLORS[color]
    # Ring (bow of the key)
    arcade.draw_circle_outline(cx - s * 0.18, cy, s * 0.22, col, 3)
    # Shaft
    arcade.draw_line(cx - s * 0.04, cy, cx + s * 0.38, cy, col, 3)
    # Teeth
    arcade.draw_line(cx + s * 0.3, cy, cx + s * 0.3, cy - s * 0.18, col, 3)
    arcade.draw_line(cx + s * 0.38, cy, cx + s * 0.38, cy - s * 0.12, col, 3)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_gate_tile(cx: float, cy: float, s: float, color: int, opened: bool):
    """Gate: filled hex with vertical bars in the color. Opened = floor-like."""
    if opened:
        _draw_hex_filled(cx, cy, s, C_FLOOR)
        _draw_hex_outline(cx, cy, s, GATE_COLORS[color], 1)
        return
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = GATE_COLORS[color]
    # Three vertical bars
    for dx in (-s * 0.25, 0, s * 0.25):
        arcade.draw_line(cx + dx, cy - s * 0.45, cx + dx, cy + s * 0.45, col, 3)
    _draw_hex_outline(cx, cy, s, col, 2)


def _draw_portal_in_tile(cx: float, cy: float, s: float, active: bool):
    """Blue entry portal. Concentric rings suggest a vortex; when the
    portal is active (switch ON) the colors are saturated, otherwise dim."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = C_PORTAL_IN if active else C_PORTAL_IN_DIM
    # 3 concentric rings of decreasing radius
    for i, rr in enumerate((s * 0.55, s * 0.40, s * 0.25)):
        arcade.draw_circle_outline(cx, cy, rr, col, 2 if active else 1)
    # Center dot
    arcade.draw_circle_filled(cx, cy, s * 0.08, col)
    _draw_hex_outline(cx, cy, s, col, 2 if active else 1)


def _draw_portal_out_tile(cx: float, cy: float, s: float, active: bool):
    """Orange destination portal. Same visual idiom as entry but in orange.
    Always drawn — player teleports INTO this tile from the blue one."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = C_PORTAL_OUT if active else (140, 80, 30)
    # Triangle/arrowhead cluster pointing outward — indicates "arrival"
    arcade.draw_circle_outline(cx, cy, s * 0.55, col, 2 if active else 1)
    arcade.draw_circle_outline(cx, cy, s * 0.40, col, 2 if active else 1)
    arcade.draw_circle_filled(cx, cy, s * 0.15, col)
    _draw_hex_outline(cx, cy, s, col, 2 if active else 1)


def _draw_switch_tile(cx: float, cy: float, s: float, on: bool):
    """Electrical switch: a lever, tilted based on state."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = C_SWITCH_ON if on else C_SWITCH_OFF
    # Base plate
    arcade.draw_rect_filled(XYWH(cx, cy - s * 0.28, s * 0.9, s * 0.22),
                            (40, 40, 55))
    arcade.draw_rect_outline(XYWH(cx, cy - s * 0.28, s * 0.9, s * 0.22),
                             col, 1)
    # Lever — tilted up-right when ON, down-left when OFF
    if on:
        lx, ly = cx + s * 0.28, cy + s * 0.30
    else:
        lx, ly = cx - s * 0.28, cy - s * 0.05
    arcade.draw_line(cx, cy - s * 0.2, lx, ly, col, 4)
    arcade.draw_circle_filled(lx, ly, s * 0.12, col)
    # Status glow
    if on:
        arcade.draw_circle_outline(cx, cy, s * 0.5, col, 1)
    _draw_hex_outline(cx, cy, s, col if on else C_HEX_OUTLINE, 2 if on else 1)


def _draw_colored_target_tile(cx: float, cy: float, s: float, color: int):
    """Colored target: like classic target but the disc uses the box color."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    col = BOX_COLOR_PALETTE[color]
    out = TARGET_COLOR_PALETTE[color]
    arcade.draw_circle_filled(cx, cy, s * 0.28, col)
    arcade.draw_circle_outline(cx, cy, s * 0.28, out, 2)
    # Small diamond inside to distinguish from classic '.' target
    arcade.draw_line(cx, cy - s * 0.10, cx + s * 0.10, cy, out, 2)
    arcade.draw_line(cx + s * 0.10, cy, cx, cy + s * 0.10, out, 2)
    arcade.draw_line(cx, cy + s * 0.10, cx - s * 0.10, cy, out, 2)
    arcade.draw_line(cx - s * 0.10, cy, cx, cy - s * 0.10, out, 2)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_wall_tile(cx: float, cy: float, s: float):
    """Stylized wall: stone-block hex with two diagonal brick lines and a
    drop shadow on the lower half. Uses multiple fill layers for depth."""
    # Base fill
    _draw_hex_filled(cx, cy, s, C_WALL)
    # Lower-half shadow: a dimmer hex clipped to the bottom by drawing
    # a smaller filled hex shifted down-right
    shadow = (70, 55, 40)
    arcade.draw_polygon_filled(
        [(cx + s * math.sqrt(3) * 0.5, cy - s * 0.1),
         (cx + s * math.sqrt(3) * 0.5, cy - s * 0.3),
         (cx, cy - s),
         (cx - s * math.sqrt(3) * 0.5, cy - s * 0.3),
         (cx - s * math.sqrt(3) * 0.5, cy - s * 0.1)],
        shadow)
    # Highlight streak on upper-left edge
    highlight = (130, 105, 80)
    arcade.draw_line(cx - s * math.sqrt(3) * 0.48, cy + s * 0.25,
                     cx - s * 0.05, cy + s * 0.90, highlight, 2)
    # Brick seams (two horizontals, offset to suggest masonry)
    seam = (75, 60, 44)
    arcade.draw_line(cx - s * 0.55, cy + s * 0.18,
                     cx + s * 0.55, cy + s * 0.18, seam, 1)
    arcade.draw_line(cx - s * 0.55, cy - s * 0.18,
                     cx + s * 0.55, cy - s * 0.18, seam, 1)
    # Short vertical tick in middle seam to imply offset bricks
    arcade.draw_line(cx + s * 0.05, cy + s * 0.18,
                     cx + s * 0.05, cy + s * 0.00, seam, 1)
    # Final outline
    _draw_hex_outline(cx, cy, s, (50, 40, 28), 1)


def _draw_floor_tile(cx: float, cy: float, s: float):
    """Stylized floor: base fill, subtle gradient via an inner lighter hex,
    and a thin outline. Two tiny speckle dots for texture without randomness."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    # Slightly lighter inner hex for a soft gradient effect
    highlight = (218, 208, 188)
    _draw_hex_filled(cx, cy, s * 0.88, highlight)
    _draw_hex_filled(cx, cy, s * 0.70, C_FLOOR)
    # Tiny ground-texture dots at deterministic positions (no randomness
    # so adjacent tiles stay visually consistent)
    spec = (178, 168, 148)
    arcade.draw_circle_filled(cx - s * 0.30, cy + s * 0.15, 1.2, spec)
    arcade.draw_circle_filled(cx + s * 0.25, cy - s * 0.20, 1.2, spec)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_target_tile(cx: float, cy: float, s: float):
    """Stylized target: floor base, bullseye rings instead of a solid dot."""
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    highlight = (218, 208, 188)
    _draw_hex_filled(cx, cy, s * 0.88, highlight)
    _draw_hex_filled(cx, cy, s * 0.70, C_FLOOR)
    # Outer glow ring, then disc, then inner dot — classic bullseye
    arcade.draw_circle_outline(cx, cy, s * 0.34, (180, 40, 40), 1)
    arcade.draw_circle_filled(cx, cy, s * 0.25, C_TARGET)
    arcade.draw_circle_outline(cx, cy, s * 0.25, (180, 40, 40), 2)
    arcade.draw_circle_filled(cx, cy, s * 0.09, (255, 210, 210))
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_crumble_tile(cx: float, cy: float, s: float):
    """Crumble floor: looks like a floor tile with jagged cracks.

    Single-use — collapses to void after the player steps off it. We
    render the same base as floor so the player can still identify it
    as walkable, then overlay three cracks forming a rough Y-shape for
    instant recognition. The cracks use a dark brown that contrasts
    with the warm floor palette without looking like a hazard.
    """
    # Floor base
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    highlight = (218, 208, 188)
    _draw_hex_filled(cx, cy, s * 0.88, highlight)
    _draw_hex_filled(cx, cy, s * 0.70, C_FLOOR)
    # Cracks — dark jagged lines emanating from center. Drawn as chained
    # line segments so each crack has a little zigzag to read as a fracture.
    crack_col = (60, 45, 35)
    # Crack 1: top
    arcade.draw_line(cx, cy, cx - s * 0.08, cy + s * 0.28, crack_col, 2)
    arcade.draw_line(cx - s * 0.08, cy + s * 0.28, cx + s * 0.04, cy + s * 0.55, crack_col, 2)
    arcade.draw_line(cx + s * 0.04, cy + s * 0.55, cx - s * 0.06, cy + s * 0.80, crack_col, 2)
    # Crack 2: bottom-left
    arcade.draw_line(cx, cy, cx - s * 0.26, cy - s * 0.12, crack_col, 2)
    arcade.draw_line(cx - s * 0.26, cy - s * 0.12, cx - s * 0.55, cy - s * 0.28, crack_col, 2)
    arcade.draw_line(cx - s * 0.55, cy - s * 0.28, cx - s * 0.70, cy - s * 0.08, crack_col, 2)
    # Crack 3: bottom-right
    arcade.draw_line(cx, cy, cx + s * 0.28, cy - s * 0.10, crack_col, 2)
    arcade.draw_line(cx + s * 0.28, cy - s * 0.10, cx + s * 0.55, cy - s * 0.35, crack_col, 2)
    arcade.draw_line(cx + s * 0.55, cy - s * 0.35, cx + s * 0.72, cy - s * 0.20, crack_col, 2)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_radioactive_tile(cx: float, cy: float, s: float):
    """Radioactive floor: floor base with the international trefoil symbol.

    The trefoil is three 60°-wide sectors, 120° apart, around a central
    disc. Rendered in the classic yellow-on-black scheme so the hazard
    is unmistakable. Deadly to step on unless the player wears CBRN
    protective clothing.
    """
    # Floor base (kept warm so the tile reads as walkable-but-hazardous)
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    highlight = (218, 208, 188)
    _draw_hex_filled(cx, cy, s * 0.88, highlight)
    _draw_hex_filled(cx, cy, s * 0.70, C_FLOOR)
    # Yellow hazard background disc
    yellow = (255, 220, 30)
    arcade.draw_circle_filled(cx, cy, s * 0.48, yellow)
    arcade.draw_circle_outline(cx, cy, s * 0.48, (30, 30, 30), 2)
    # Trefoil: three black pie-slice sectors at 0°, 120°, 240°.
    # Each sector spans 60° of arc.
    black = (20, 20, 20)
    for ang_deg in (90, 210, 330):
        # Build a polygon: center + two arc endpoints + interpolated mids
        ang = math.radians(ang_deg)
        # Arc from ang-30° to ang+30°
        pts = [(cx, cy)]
        for t in range(0, 7):
            a = math.radians(ang_deg - 30 + t * 10)
            r = s * 0.42
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        arcade.draw_polygon_filled(pts, black)
    # Central black disc
    arcade.draw_circle_filled(cx, cy, s * 0.13, black)
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_cbrn_item_tile(cx: float, cy: float, s: float):
    """CBRN protective clothing item: floor base with a hazmat-suit glyph.

    Rendered as a simple humanoid silhouette in a bright hazard green,
    with a circular helmet visor so it reads as 'suit' rather than
    'person'. Picked up automatically when the player steps on it.
    """
    # Floor base
    _draw_hex_filled(cx, cy, s, C_FLOOR)
    highlight = (218, 208, 188)
    _draw_hex_filled(cx, cy, s * 0.88, highlight)
    _draw_hex_filled(cx, cy, s * 0.70, C_FLOOR)
    # Suit color — bright hazmat green/yellow
    suit = (210, 230, 60)
    suit_out = (120, 135, 30)
    # Body: rectangle (torso) plus legs
    torso_w = s * 0.34
    torso_h = s * 0.36
    arcade.draw_rect_filled(XYWH(cx, cy - s * 0.04, torso_w, torso_h), suit)
    arcade.draw_rect_outline(XYWH(cx, cy - s * 0.04, torso_w, torso_h), suit_out, 2)
    # Legs: two small rects at the bottom
    leg_w = s * 0.12
    leg_h = s * 0.20
    arcade.draw_rect_filled(XYWH(cx - s * 0.09, cy - s * 0.30, leg_w, leg_h), suit)
    arcade.draw_rect_outline(XYWH(cx - s * 0.09, cy - s * 0.30, leg_w, leg_h), suit_out, 2)
    arcade.draw_rect_filled(XYWH(cx + s * 0.09, cy - s * 0.30, leg_w, leg_h), suit)
    arcade.draw_rect_outline(XYWH(cx + s * 0.09, cy - s * 0.30, leg_w, leg_h), suit_out, 2)
    # Arms
    arcade.draw_rect_filled(XYWH(cx - s * 0.25, cy - s * 0.05, s * 0.12, s * 0.28), suit)
    arcade.draw_rect_outline(XYWH(cx - s * 0.25, cy - s * 0.05, s * 0.12, s * 0.28), suit_out, 2)
    arcade.draw_rect_filled(XYWH(cx + s * 0.25, cy - s * 0.05, s * 0.12, s * 0.28), suit)
    arcade.draw_rect_outline(XYWH(cx + s * 0.25, cy - s * 0.05, s * 0.12, s * 0.28), suit_out, 2)
    # Helmet with circular visor
    arcade.draw_circle_filled(cx, cy + s * 0.30, s * 0.17, suit)
    arcade.draw_circle_outline(cx, cy + s * 0.30, s * 0.17, suit_out, 2)
    # Visor — dark
    arcade.draw_circle_filled(cx, cy + s * 0.30, s * 0.10, (40, 50, 60))
    _draw_hex_outline(cx, cy, s, C_HEX_OUTLINE, 1)


def _draw_tile(cx: float, cy: float, s: float, tid: int,
               *, laser_active: bool = True, gate_opened: bool = False,
               slab_pressed: bool = False, switch_on: bool = False,
               portal_active: bool = False):
    """Dispatch to the correct drawer based on tile ID.

    Runtime state (laser_active / gate_opened / slab_pressed / switch_on
    / portal_active) is passed by the view which knows the engine's
    current state. Defaults are chosen so the editor (no engine) shows
    lasers/gates in their "locked" form and portals as inactive.
    """
    if tid == WALL:
        _draw_wall_tile(cx, cy, s)
    elif tid == FLOOR:
        _draw_floor_tile(cx, cy, s)
    elif tid == TARGET:
        _draw_target_tile(cx, cy, s)
    elif tid == EMPTY:
        pass  # void
    elif is_slab(tid):
        _draw_slab_tile(cx, cy, s, slab_group(tid), slab_pressed)
    elif is_laser(tid):
        _draw_laser_tile(cx, cy, s, laser_group(tid), laser_active)
    elif is_key(tid):
        _draw_key_tile(cx, cy, s, key_color(tid))
    elif is_gate(tid):
        _draw_gate_tile(cx, cy, s, gate_color(tid), gate_opened)
    elif is_portal_in(tid):
        _draw_portal_in_tile(cx, cy, s, portal_active)
    elif is_portal_out(tid):
        _draw_portal_out_tile(cx, cy, s, portal_active)
    elif is_switch(tid):
        _draw_switch_tile(cx, cy, s, switch_on)
    elif is_colored_target(tid):
        _draw_colored_target_tile(cx, cy, s, target_color(tid))
    elif is_crumble(tid):
        _draw_crumble_tile(cx, cy, s)
    elif is_radioactive(tid):
        _draw_radioactive_tile(cx, cy, s)
    elif is_cbrn_item(tid):
        _draw_cbrn_item_tile(cx, cy, s)


def _draw_box(cx: float, cy: float, s: float, on_target: bool,
              color: int = -1):
    """Draw a stylized box: drop shadow, main body, rivets at the 6 corners,
    inner highlight, diagonal cross. Colored boxes use the box-color
    palette; uncolored use the classic brown/green."""
    if color >= 0:
        col = BOX_COLOR_PALETTE[color]
        out = TARGET_COLOR_PALETTE[color] if on_target else (30, 30, 40)
    else:
        col = C_BOX_OK if on_target else C_BOX
        out = C_BOX_OK_OUTLINE if on_target else C_BOX_OUTLINE
    inner_s = s * 0.72

    # Drop shadow (slight offset down-right, dim color, no outline)
    shadow = (20, 20, 30)
    _draw_hex_filled(cx + 1.5, cy - 2, inner_s, shadow)
    # Main body
    _draw_hex_filled(cx, cy, inner_s, col)
    # Inner highlight — a smaller hex in a brighter shade
    hl = tuple(min(255, int(c * 1.22)) for c in col[:3])
    _draw_hex_filled(cx, cy, inner_s * 0.72, hl)
    # Center again with main color, making a ring of highlight around it
    _draw_hex_filled(cx, cy, inner_s * 0.50, col)
    # Thick outline
    _draw_hex_outline(cx, cy, inner_s, out, 2)
    # Diagonal cross (subtle)
    m = inner_s * 0.55
    arcade.draw_line(cx - m, cy - m * 0.55, cx + m, cy + m * 0.55, out, 1)
    arcade.draw_line(cx + m, cy - m * 0.55, cx - m, cy + m * 0.55, out, 1)
    # Rivets at 6 corners
    for i in range(6):
        angle = math.radians(60 * i - 30)
        rx = cx + inner_s * 0.80 * math.cos(angle)
        ry = cy + inner_s * 0.80 * math.sin(angle)
        arcade.draw_circle_filled(rx, ry, 1.6, out)


def _draw_player(cx: float, cy: float, s: float, has_cbrn: bool = False):
    """Stylized player: drop shadow, body, highlight crescent, eyes with
    pupil dots, subtle outer ring.

    When `has_cbrn` is True the player is rendered wearing the CBRN
    protective suit: the body is tinted hazmat-yellow/green with a
    darker visor replacing the eyes, so it's instantly obvious the
    player can cross radioactive tiles.
    """
    if has_cbrn:
        # Suited player — hazmat-style silhouette.
        body_col = (210, 230, 60)   # hazmat green-yellow
        outline_col = (120, 135, 30)
        # Shadow
        arcade.draw_circle_filled(cx + 1.5, cy - 2, s * 0.40, (20, 20, 30))
        # Outer faint ring
        arcade.draw_circle_outline(cx, cy, s * 0.44, outline_col, 1)
        # Body disc
        r = s * 0.40
        arcade.draw_circle_filled(cx, cy, r, body_col)
        # Upper-left highlight
        hl = tuple(min(255, int(c * 1.20)) for c in body_col[:3])
        arcade.draw_circle_filled(cx - r * 0.28, cy + r * 0.28, r * 0.55, hl)
        arcade.draw_circle_filled(cx, cy, r * 0.9, body_col)
        # Thick outline
        arcade.draw_circle_outline(cx, cy, r, outline_col, 2)
        # Helmet visor: a single dark oval across the face instead of eyes
        arcade.draw_ellipse_filled(cx, cy + s * 0.04, s * 0.34, s * 0.18,
                                    (40, 50, 65))
        arcade.draw_ellipse_outline(cx, cy + s * 0.04, s * 0.34, s * 0.18,
                                     (20, 25, 35), 2)
        # Small reflection highlight on the visor
        arcade.draw_ellipse_filled(cx - s * 0.08, cy + s * 0.08,
                                    s * 0.08, s * 0.04, (180, 200, 220))
        # A tiny breathing-filter mark at the bottom of the visor
        arcade.draw_circle_filled(cx, cy - s * 0.07, s * 0.04, (120, 130, 140))
        return

    # Standard (no CBRN) player — original rendering
    # Shadow
    arcade.draw_circle_filled(cx + 1.5, cy - 2, s * 0.38, (20, 20, 30))
    # Outer ring (faint glow)
    arcade.draw_circle_outline(cx, cy, s * 0.42, C_PLAYER_OUTLINE, 1)
    # Body
    r = s * 0.38
    arcade.draw_circle_filled(cx, cy, r, C_PLAYER)
    # Upper-left highlight crescent via two overlapping circles
    hl = tuple(min(255, int(c * 1.30)) for c in C_PLAYER[:3])
    arcade.draw_circle_filled(cx - r * 0.28, cy + r * 0.28, r * 0.55, hl)
    arcade.draw_circle_filled(cx, cy, r * 0.9, C_PLAYER)
    # Outline
    arcade.draw_circle_outline(cx, cy, r, C_PLAYER_OUTLINE, 2)
    # Eyes — white with black pupils
    ey = cy + s * 0.06
    arcade.draw_circle_filled(cx - s * 0.12, ey, 3.2, (255, 255, 255))
    arcade.draw_circle_filled(cx + s * 0.12, ey, 3.2, (255, 255, 255))
    arcade.draw_circle_filled(cx - s * 0.12, ey, 1.4, (20, 20, 40))
    arcade.draw_circle_filled(cx + s * 0.12, ey, 1.4, (20, 20, 40))
    # Small smile
    arcade.draw_arc_outline(cx, cy - s * 0.05, s * 0.18, s * 0.14,
                             (20, 20, 40), 200, 340, 2)


def _compute_pressed_groups(eng) -> set:
    """Return set of slab-group IDs currently occupied by player or a box.

    Scans the grid once. Called per-frame in the render and per-state in
    the engine's move logic (which has its own scan). Cheap for typical
    hex-grid sizes; if it becomes a bottleneck a slab-position cache can
    be built at load time.
    """
    pressed = set()
    player_rc = (eng.player_r, eng.player_c)
    for r in range(eng.rows):
        for c in range(eng.cols):
            t = eng.grid[r][c]
            if is_slab(t):
                if (r, c) == player_rc or (r, c) in eng.boxes:
                    pressed.add(slab_group(t))
    return pressed


def _format_time(seconds: float) -> str:
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m:02d}:{s:02d}"


# ───────────────────────────────────────────────────────────────────
# Key mapping for Hexoban (6 directions)
# ───────────────────────────────────────────────────────────────────
def _key_from_name(name: str) -> int:
    mapping = {
        "UP": arcade.key.UP, "DOWN": arcade.key.DOWN,
        "LEFT": arcade.key.LEFT, "RIGHT": arcade.key.RIGHT,
        "ESCAPE": arcade.key.ESCAPE,
        "z": arcade.key.Z, "y": arcade.key.Y, "r": arcade.key.R,
        "f": arcade.key.F, "h": arcade.key.H, "m": arcade.key.M,
        # Numpad keys for hex directions (NumLock ON)
        "KP_7": arcade.key.NUM_7, "KP_9": arcade.key.NUM_9,
        "KP_4": arcade.key.NUM_4, "KP_6": arcade.key.NUM_6,
        "KP_1": arcade.key.NUM_1, "KP_3": arcade.key.NUM_3,
        # Numpad keys (NumLock OFF aliases)
        "KP_HOME": getattr(arcade.key, "NUM_HOME", 0),
        "KP_PGUP": getattr(arcade.key, "NUM_PAGE_UP", 0),
        "KP_LEFT": getattr(arcade.key, "NUM_LEFT", 0),
        "KP_RIGHT": getattr(arcade.key, "NUM_RIGHT", 0),
        "KP_END": getattr(arcade.key, "NUM_END", 0),
        "KP_PGDN": getattr(arcade.key, "NUM_PAGE_DOWN", 0),
    }
    return mapping.get(name, getattr(arcade.key, name.upper(), 0))


# Hex numpad direction mapping
_HEX_NUMPAD_DIRS = {}

def _init_hex_numpad():
    """Build hex numpad direction map."""
    _hex_map = {
        # Numpad 7 = top left
        "NUM_7": "TOP_LEFT", "NUM_HOME": "TOP_LEFT",
        # Numpad 9 = top right
        "NUM_9": "TOP_RIGHT", "NUM_PAGE_UP": "TOP_RIGHT",
        # Numpad 4 = left
        "NUM_4": "LEFT", "NUM_LEFT": "LEFT",
        # Numpad 6 = right
        "NUM_6": "RIGHT", "NUM_RIGHT": "RIGHT",
        # Numpad 1 = bottom left
        "NUM_1": "BOTTOM_LEFT", "NUM_END": "BOTTOM_LEFT",
        # Numpad 3 = bottom right
        "NUM_3": "BOTTOM_RIGHT", "NUM_PAGE_DOWN": "BOTTOM_RIGHT",
    }
    for attr, d in _hex_map.items():
        val = getattr(arcade.key, attr, None)
        if val is not None:
            _HEX_NUMPAD_DIRS[val] = d


def _hex_direction(key: int) -> Optional[str]:
    """Return hex direction string for a key, or None."""
    if not _HEX_NUMPAD_DIRS:
        _init_hex_numpad()
    return _HEX_NUMPAD_DIRS.get(key)


# Also map regular arrow keys to approximate hex directions for usability
_ARROW_HEX_DIRS = {}

def _init_arrow_hex():
    _ARROW_HEX_DIRS[arcade.key.LEFT] = "LEFT"
    _ARROW_HEX_DIRS[arcade.key.RIGHT] = "RIGHT"
    # Up arrow -> top right (natural feel), Down -> bottom left
    _ARROW_HEX_DIRS[arcade.key.UP] = "TOP_RIGHT"
    _ARROW_HEX_DIRS[arcade.key.DOWN] = "BOTTOM_LEFT"

def _arrow_hex_direction(key: int) -> Optional[str]:
    if not _ARROW_HEX_DIRS:
        _init_arrow_hex()
    return _ARROW_HEX_DIRS.get(key)


# ───────────────────────────────────────────────────────────────────
# Navigation helpers (for menus - using UP/DOWN arrows)
# ───────────────────────────────────────────────────────────────────
def _is_nav_up(key):
    return key == arcade.key.UP

def _is_nav_down(key):
    return key == arcade.key.DOWN


# ═══════════════════════════════════════════════════════════════════
# WINDOW
# ═══════════════════════════════════════════════════════════════════
class HexobanWindow(arcade.Window):
    def __init__(self, cfg: dict):
        super().__init__(
            cfg["win_width"], cfg["win_height"],
            "Hexoban — Hexagonal Sokoban", resizable=True,
            fullscreen=cfg["fullscreen"],
        )
        self.set_minimum_size(800, 600)
        self.cfg = cfg
        self.keys = {k: _key_from_name(v) for k, v in cfg.items() if k.startswith("key_")}
        _load_textures(cfg["tile_size"])
        self.show_view(MenuView())


def _load_textures(tile_size: int):
    tex_dir = Path("assets/textures")
    if not (tex_dir / "wall.png").exists():
        gen_textures(tile_size)


# ═══════════════════════════════════════════════════════════════════
# Shared helpers for list views
# ═══════════════════════════════════════════════════════════════════
def _draw_hud_bar(w, h, text_left="", text_right=""):
    arcade.draw_rect_filled(XYWH(w / 2, h - HUD_H / 2, w, HUD_H), C_HUD_BAR)
    if text_left:
        arcade.Text(text_left, 12, h - HUD_H / 2, C_TITLE, 20,
                    anchor_y="center", bold=True).draw()
    if text_right:
        arcade.Text(text_right, w - 12, h - HUD_H / 2, C_HINT, 13,
                    anchor_x="right", anchor_y="center").draw()


def _draw_hint_bar(w, text):
    arcade.draw_rect_filled(XYWH(w / 2, HINT_H / 2, w, HINT_H), C_HUD_BAR)
    arcade.Text(text, w / 2, HINT_H / 2, C_HINT, 13,
                anchor_x="center", anchor_y="center").draw()


def _draw_list_item(w, y, label, selected, item_h=44, bar_w=420):
    if selected:
        arcade.draw_rect_filled(XYWH(w / 2, y, bar_w, item_h), C_SEL_BAR)
        arcade.draw_rect_outline(XYWH(w / 2, y, bar_w, item_h), C_TITLE, 2)
    col = C_MENU_SEL if selected else C_MENU
    prefix = "\u25b6  " if selected else "   "
    arcade.Text(prefix + label, w / 2, y, col, 20 if selected else 17,
                anchor_x="center", anchor_y="center", bold=selected).draw()


def _toggle_fullscreen(window):
    window.set_fullscreen(not window.fullscreen)


# ═══════════════════════════════════════════════════════════════════
# MENU VIEW
# ═══════════════════════════════════════════════════════════════════
class MenuView(arcade.View):
    def __init__(self):
        super().__init__()
        self.selected = 0
        self.background_color = C_BG

    def on_show_view(self):
        self.background_color = C_BG

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        # title
        arcade.Text("H E X O B A N", w / 2, h * 0.80, C_TITLE, 52,
                    anchor_x="center", anchor_y="center", bold=True).draw()
        arcade.Text("Hexagonal Sokoban", w / 2, h * 0.72,
                    (100, 100, 120), 17, anchor_x="center", anchor_y="center").draw()
        # decorative hex
        _draw_hex_outline(w / 2, h * 0.80, 60, (*C_TITLE, 50), 2)
        # menu
        start_y = h * 0.58
        for i, label in enumerate(MENU_ITEMS):
            _draw_list_item(w, start_y - i * 46, label, i == self.selected, 44, 380)
        _draw_hint_bar(w, "\u2191/\u2193 Select \u2022 Enter Confirm \u2022 F Fullscreen \u2022 Esc Quit")

    def on_key_press(self, key, mods):
        keys = self.window.keys
        if _is_nav_up(key):
            self.selected = (self.selected - 1) % len(MENU_ITEMS)
        elif _is_nav_down(key):
            self.selected = (self.selected + 1) % len(MENU_ITEMS)
        elif key in (arcade.key.RETURN, arcade.key.ENTER):
            [
                lambda: self.window.show_view(LevelSelectView()),
                lambda: self.window.show_view(LoadGameView()),
                lambda: self.window.show_view(EditorView()),
                lambda: self.window.show_view(ResolverView()),
                lambda: self.window.show_view(ReplayView()),
                lambda: self.window.show_view(OptimizeView()),
                lambda: self.window.show_view(CreditsView()),
            ][self.selected]()
        elif key == keys.get("key_quit"):
            arcade.exit()
        elif key == keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)


# ═══════════════════════════════════════════════════════════════════
# LEVEL SELECT VIEW
# ═══════════════════════════════════════════════════════════════════
class LevelSelectView(arcade.View):
    def __init__(self):
        super().__init__()
        self.selected = 0
        self.scroll_offset = 0
        self.background_color = C_BG

    def on_show_view(self):
        self.background_color = C_BG

    def _visible_count(self):
        return max(1, (self.window.height - HUD_H - HINT_H - 40) // 46)

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        _draw_hud_bar(w, h, "Select Level", f"{self.selected+1}/{len(BUILTIN_LEVELS)}")
        _draw_hint_bar(w, "\u2191/\u2193 Select \u2022 Enter Play \u2022 Esc Back")
        vis = self._visible_count()
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + vis:
            self.scroll_offset = self.selected - vis + 1
        start_y = h - HUD_H - 30
        for vi in range(vis):
            idx = self.scroll_offset + vi
            if idx >= len(BUILTIN_LEVELS):
                break
            lv = BUILTIN_LEVELS[idx]
            iy = start_y - vi * 46
            _draw_list_item(w, iy, lv["name"], idx == self.selected)
        if self.scroll_offset > 0:
            arcade.Text("\u25b2 more", w / 2, start_y + 24, C_HINT, 12, anchor_x="center").draw()
        if self.scroll_offset + vis < len(BUILTIN_LEVELS):
            arcade.Text("\u25bc more", w / 2, start_y - vis * 46 + 14, C_HINT, 12, anchor_x="center").draw()

    def on_key_press(self, key, mods):
        if _is_nav_up(key):
            self.selected = (self.selected - 1) % len(BUILTIN_LEVELS)
        elif _is_nav_down(key):
            self.selected = (self.selected + 1) % len(BUILTIN_LEVELS)
        elif key in (arcade.key.RETURN, arcade.key.ENTER):
            lv = BUILTIN_LEVELS[self.selected]
            self.window.show_view(GameView(lv["data"], lv["name"], self.selected))
        elif key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())
        elif key == self.window.keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)


# ═══════════════════════════════════════════════════════════════════
# LOAD GAME VIEW
# ═══════════════════════════════════════════════════════════════════
class LoadGameView(arcade.View):
    def __init__(self):
        super().__init__()
        self.files = list_saved_levels()
        self.selected = 0
        self.background_color = C_BG

    def on_show_view(self):
        self.background_color = C_BG

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        _draw_hud_bar(w, h, "Load Game")
        _draw_hint_bar(w, "\u2191/\u2193 Select \u2022 Enter Play \u2022 E=Edit \u2022 Esc Back")
        if not self.files:
            arcade.Text("No saved levels found.", w / 2, h / 2,
                        C_MENU, 20, anchor_x="center").draw()
            arcade.Text("Create levels in the Level Editor!",
                        w / 2, h / 2 - 32, C_HINT, 15, anchor_x="center").draw()
        else:
            start_y = h - HUD_H - 30
            for i, f in enumerate(self.files):
                _draw_list_item(w, start_y - i * 44, f.stem, i == self.selected)

    def on_key_press(self, key, mods):
        if key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())
        elif key == self.window.keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)
        elif self.files:
            if _is_nav_up(key):
                self.selected = (self.selected - 1) % len(self.files)
            elif _is_nav_down(key):
                self.selected = (self.selected + 1) % len(self.files)
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                data = load_level_file(str(self.files[self.selected]))
                if data:
                    self.window.show_view(GameView(data["data"], data["name"], -1))
            elif key == arcade.key.E:
                data = load_level_file(str(self.files[self.selected]))
                if data:
                    self.window.show_view(EditorView(load_data=data))


# ═══════════════════════════════════════════════════════════════════
# GAME VIEW — hex grid with clock timer in HUD
# ═══════════════════════════════════════════════════════════════════
class GameView(arcade.View):
    def __init__(self, lines: list[str], name: str, level_idx: int):
        super().__init__()
        self.level_name = name
        self.level_idx = level_idx
        self.engine = HexobanEngine()
        self.engine.load_from_lines(lines)
        self._original_lines = lines
        self.hex_size = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.show_help = False
        self.win_time: Optional[float] = None
        self.background_color = C_BG
        self.camera = arcade.camera.Camera2D()
        # timer
        self.start_time = time.time()
        self.elapsed = 0.0
        self.timer_paused = False
        # move recording for human solutions
        self.move_history: list[str] = []
        # cached text objects (created in _build_texts)
        self._txt_name = None
        self._txt_info = None
        self._txt_timer = None
        self._txt_hint = None
        self._txt_win_title = None
        self._txt_win_info = None
        self._txt_win_hint = None

    def on_show_view(self):
        self.background_color = C_BG
        self._calc_layout()
        self._build_texts()
        log(f"Playing: {self.level_name} ({self.engine.rows}x{self.engine.cols}, "
            f"{len(self.engine.boxes)}b)")

    def on_resize(self, width, height):
        super().on_resize(width, height)
        self.camera = arcade.camera.Camera2D()
        self._calc_layout()
        self._build_texts()

    def _build_texts(self):
        """Create / recreate cached Text objects after layout change."""
        w, h = self.window.width, self.window.height
        self._txt_name = arcade.Text(
            self.level_name, 12, h - HUD_H / 2, C_TITLE, 18,
            anchor_y="center", bold=True)
        self._txt_info = arcade.Text(
            "", w / 2, h - HUD_H / 2, C_HUD, 16,
            anchor_x="center", anchor_y="center")
        self._txt_timer = arcade.Text(
            "00:00", w - 14, h - HUD_H / 2 - 2, C_WARN, 20,
            anchor_x="right", anchor_y="center", bold=True)
        self._txt_hint = arcade.Text(
            "H=Help  M=Menu", w - 80, h - HUD_H + 6, C_HINT, 10,
            anchor_x="right")
        self._txt_win_title = arcade.Text(
            "LEVEL COMPLETE!", w / 2, h / 2 + 50, C_SUCCESS, 44,
            anchor_x="center", anchor_y="center", bold=True)
        self._txt_win_info = arcade.Text(
            "", w / 2, h / 2, C_HUD, 22,
            anchor_x="center", anchor_y="center")
        self._txt_win_hint = arcade.Text(
            "Enter=Next  R=Retry  Esc=Menu", w / 2, h / 2 - 45, C_HINT, 16,
            anchor_x="center")

    def _calc_layout(self):
        w, h = self.window.width, self.window.height
        playable_h = h - HUD_H - 8
        eng = self.engine
        # Calculate hex size to fit grid
        hex_w = math.sqrt(3)  # width factor per hex
        hex_h = 1.5  # row height factor (pointy-top)

        grid_w_units = eng.cols * hex_w + (hex_w / 2 if eng.rows > 1 else 0)
        grid_h_units = (eng.rows - 1) * hex_h + 2  # +2 for top and bottom vertex

        max_s_w = (w - 40) / grid_w_units if grid_w_units > 0 else 40
        max_s_h = (playable_h - 20) / grid_h_units if grid_h_units > 0 else 40
        self.hex_size = min(max_s_w, max_s_h, 64)

        # Calculate offsets to center the grid
        actual_w = grid_w_units * self.hex_size
        actual_h = grid_h_units * self.hex_size
        self.offset_x = (w - actual_w) / 2 + self.hex_size * math.sqrt(3) / 2
        self.offset_y = (playable_h - actual_h) / 2 + self.hex_size

    def _cell_xy(self, r: int, c: int):
        s = self.hex_size
        hx, hy = hex_center(r, c, s)
        # Convert to screen coords (y flipped, offset for HUD)
        x = self.offset_x + hx
        y = self.window.height - HUD_H - self.offset_y - hy
        return x, y

    def on_update(self, dt):
        if not self.timer_paused and not self.win_time:
            self.elapsed = time.time() - self.start_time

    def on_draw(self):
        self.clear()
        self.camera.use()
        w, h = self.window.width, self.window.height
        s = self.hex_size
        eng = self.engine

        # Precompute slab-group pressure once per frame
        pressed_groups = _compute_pressed_groups(eng)
        portal_active = eng.switch_on  # portals work only when switch on

        # grid
        for r in range(eng.rows):
            for c in range(eng.cols):
                tid = eng.grid[r][c]
                active = gate_op = slab_prs = False
                sw_on = eng.switch_on
                if is_laser(tid):
                    active = laser_group(tid) not in pressed_groups
                elif is_gate(tid):
                    gate_op = (r, c) in eng.opened_gates
                elif is_slab(tid):
                    slab_prs = slab_group(tid) in pressed_groups
                elif is_key(tid):
                    if (r, c) in eng.collected_keys:
                        # Already picked up — draw as floor
                        _draw_tile(*self._cell_xy(r, c), s, FLOOR)
                        continue
                elif is_cbrn_item(tid):
                    if (r, c) in eng.collected_cbrn:
                        # Already picked up — draw as floor
                        _draw_tile(*self._cell_xy(r, c), s, FLOOR)
                        continue
                _draw_tile(*self._cell_xy(r, c), s, tid,
                           laser_active=active, gate_opened=gate_op,
                           slab_pressed=slab_prs, switch_on=sw_on,
                           portal_active=portal_active)
        # boxes — pass color if the box is colored
        for br, bc in eng.boxes:
            color = eng.box_colors.get((br, bc), -1)
            _draw_box(*self._cell_xy(br, bc), s,
                      (br, bc) in eng.targets, color=color)
        # player — pass has_cbrn so the suit texture is used once the item
        # has been picked up
        _draw_player(*self._cell_xy(eng.player_r, eng.player_c), s,
                     has_cbrn=eng.has_cbrn)

        # HUD
        arcade.draw_rect_filled(XYWH(w / 2, h - HUD_H / 2, w, HUD_H), C_HUD_BAR)
        if self._txt_name:
            self._txt_name.draw()
        if self._txt_info:
            best = get_best_moves(self.level_name, self._original_lines)
            best_str = f"   Best: {best}m" if best else ""
            self._txt_info.text = f"Moves: {eng.moves}   Pushes: {eng.pushes}{best_str}"
            self._txt_info.draw()
        if self._txt_timer:
            self._txt_timer.text = _format_time(self.elapsed)
            self._txt_timer.draw()
        if self._txt_hint:
            self._txt_hint.draw()

        # Key inventory HUD — small colored key icons with counts,
        # shown only if this level has any keys or gates.
        if any(any(is_key(t) or is_gate(t) for t in row) for row in eng.grid):
            self._draw_key_inventory(eng)

        # win overlay
        if eng.is_solved() or self.win_time:
            if not self.win_time:
                self.win_time = time.time()
                self.timer_paused = True
                log(f"LEVEL COMPLETE: {self.level_name} in {self.engine.moves}m "
                    f"{self.engine.pushes}p {_format_time(self.elapsed)}")
                # Save human solution
                if self.move_history:
                    best = get_best_moves(self.level_name, self._original_lines)
                    is_new_best = best is None or len(self.move_history) < best
                    save_solution(
                        self.level_name, self._original_lines,
                        self.move_history, self.engine.pushes,
                        is_best=is_new_best)
                    if best is None:
                        log(f"  Solution saved: {len(self.move_history)}m (first solve!)")
                    elif is_new_best:
                        log(f"  NEW BEST! {len(self.move_history)}m (was {best}m)")
                    else:
                        log(f"  Solution: {len(self.move_history)}m (best: {best}m)")
            arcade.draw_rect_filled(XYWH(w / 2, h / 2, w, h), C_OVERLAY)
            if self._txt_win_title:
                self._txt_win_title.draw()
            if self._txt_win_info:
                self._txt_win_info.text = f"Moves: {eng.moves}   Pushes: {eng.pushes}   Time: {_format_time(self.elapsed)}"
                self._txt_win_info.draw()
            if self._txt_win_hint:
                self._txt_win_hint.draw()

        # help overlay
        if self.show_help:
            self._draw_help()

    def _draw_key_inventory(self, eng):
        """Render held keys as small colored icons along the bottom-left HUD."""
        w, h = self.window.width, self.window.height
        total = sum(eng.held_keys)
        x = 16
        y = HUD_H / 2 - 2
        # Background pill
        if total > 0:
            arcade.draw_rect_filled(XYWH(x + 90, y, 200, HUD_H - 10), C_HUD_BAR)
        # Label
        arcade.Text("Keys:", x, y, C_HUD, 13, anchor_y="center").draw()
        x += 46
        for color in range(NUM_KEY_COLORS):
            n = eng.held_keys[color]
            if n > 0:
                col = KEY_COLORS[color]
                arcade.draw_circle_outline(x, y, 7, col, 2)
                arcade.draw_line(x + 5, y, x + 14, y, col, 2)
                arcade.draw_line(x + 11, y, x + 11, y - 4, col, 2)
                if n > 1:
                    arcade.Text(f"x{n}", x + 18, y, col, 11,
                                anchor_y="center", bold=True).draw()
                x += 32

    def _draw_help(self):
        w, h = self.window.width, self.window.height
        bw, bh = 500, 420
        arcade.draw_rect_filled(XYWH(w/2, h/2, bw, bh), (20, 20, 35, 230))
        arcade.draw_rect_outline(XYWH(w/2, h/2, bw, bh), C_TITLE, 2)
        lines = [
            ("HEXOBAN CONTROLS", 22, C_TITLE, True),
            ("", 10, C_HUD, False),
            ("Numpad 7 / Q \u2014 Move top-left", 15, C_HUD, False),
            ("Numpad 9 / E \u2014 Move top-right", 15, C_HUD, False),
            ("Numpad 4 / A \u2014 Move left", 15, C_HUD, False),
            ("Numpad 6 / D \u2014 Move right", 15, C_HUD, False),
            ("Numpad 1 / X \u2014 Move bottom-left", 15, C_HUD, False),
            ("Numpad 3 / C \u2014 Move bottom-right", 15, C_HUD, False),
            ("", 8, C_HUD, False),
            ("Arrow keys also work (approximate)", 13, C_HINT, False),
            ("", 8, C_HUD, False),
            ("Z or U \u2014 Undo", 15, C_HUD, False),
            ("Y \u2014 Redo", 15, C_HUD, False),
            ("R \u2014 Restart level", 15, C_HUD, False),
            ("F \u2014 Toggle fullscreen", 15, C_HUD, False),
            ("M \u2014 Back to menu", 15, C_HUD, False),
            ("H \u2014 Toggle this help", 15, C_HUD, False),
            ("", 8, C_HUD, False),
            ("Push all boxes onto red targets!", 15, C_WARN, True),
        ]
        y = h / 2 + bh / 2 - 30
        for text, sz, col, bold in lines:
            if text:
                arcade.Text(text, w / 2, y, col, sz, anchor_x="center", bold=bold).draw()
            y -= sz + 8

    def on_key_press(self, key, mods):
        keys = self.window.keys
        if key == keys.get("key_help"):
            self.show_help = not self.show_help
            return
        if self.show_help:
            self.show_help = False
            return
        if self.win_time:
            if key in (arcade.key.RETURN, arcade.key.ENTER):
                self._next_level()
            elif key == keys.get("key_restart"):
                self._restart()
            elif key in (arcade.key.ESCAPE, keys.get("key_menu")):
                self.window.show_view(MenuView())
            return

        # 6 hex directions from config keys
        direction = {
            keys.get("key_top_left"): "TOP_LEFT",
            keys.get("key_top_right"): "TOP_RIGHT",
            keys.get("key_left"): "LEFT",
            keys.get("key_right"): "RIGHT",
            keys.get("key_bottom_left"): "BOTTOM_LEFT",
            keys.get("key_bottom_right"): "BOTTOM_RIGHT",
        }.get(key)

        # numpad hex directions
        if not direction:
            direction = _hex_direction(key)

        # QWEASD alternative layout
        if not direction:
            qweasd = {
                arcade.key.Q: "TOP_LEFT",
                arcade.key.E: "TOP_RIGHT",
                arcade.key.A: "LEFT",
                arcade.key.D: "RIGHT",
                # Z is undo in Sokoban tradition, so use X for BL
                arcade.key.X: "BOTTOM_LEFT",
                arcade.key.C: "BOTTOM_RIGHT",
            }
            direction = qweasd.get(key)

        # Arrow key approximate mapping
        if not direction:
            direction = _arrow_hex_direction(key)

        if direction:
            moved = self.engine.move(direction)
            if moved:
                self.move_history.append(direction)
                log(f"Move: {direction} -> ({self.engine.player_r},{self.engine.player_c}) "
                    f"m={self.engine.moves} p={self.engine.pushes}")
            return

        if key == arcade.key.U:  # undo
            self.engine.undo()
            if self.move_history:
                self.move_history.pop()
        elif key == keys.get("key_undo"):
            self.engine.undo()
            if self.move_history:
                self.move_history.pop()
        elif key == keys.get("key_redo"):
            self.engine.redo()
        elif key == keys.get("key_restart"):
            self._restart()
        elif key == keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)
            self._calc_layout()
        elif key in (keys.get("key_quit"), keys.get("key_menu")):
            self.window.show_view(MenuView())

    def _restart(self):
        self.engine.restart()
        self.win_time = None
        self.start_time = time.time()
        self.elapsed = 0.0
        self.timer_paused = False
        self.move_history.clear()

    def _next_level(self):
        if self.level_idx >= 0:
            ni = self.level_idx + 1
            if ni < len(BUILTIN_LEVELS):
                lv = get_builtin_level(ni)
                self.window.show_view(GameView(lv["data"], lv["name"], ni))
                return
        self.window.show_view(LevelSelectView())


# ═══════════════════════════════════════════════════════════════════
# LEVEL EDITOR — hex grid, mouse paint, resize, undo
# ═══════════════════════════════════════════════════════════════════
ED_TOOLS = [
    (EMPTY,  "Void",   C_BG),
    (WALL,   "Wall",   C_WALL),
    (FLOOR,  "Floor",  C_FLOOR),
    (TARGET, "Target", C_TARGET),
]
# Special tool codes — values chosen to not collide with real tile IDs
# (slabs are 10-13, lasers 20-23, keys 30-33, gates 40-43).
ED_SPECIAL_PLAYER = 200
ED_SPECIAL_BOX = 201
# Extended tools: each slab/laser group and each key/gate color.
# The editor uses a currently-selected "group" (0..3) and "color" (0..3)
# to decide what specific tile a slab/laser/key/gate tool places.
ED_SPECIAL_SLAB = 210
ED_SPECIAL_LASER = 211
ED_SPECIAL_KEY = 212
ED_SPECIAL_GATE = 213
# v3 tools: portal/switch/colored boxes/colored targets.
# `selected_box_color` drives colored-target and colored-box paint.
ED_SPECIAL_PORTAL_IN = 220
ED_SPECIAL_PORTAL_OUT = 221
ED_SPECIAL_SWITCH = 222
ED_SPECIAL_COLORED_TARGET = 223
ED_SPECIAL_COLORED_BOX = 224
# v4 tools: single-use crumble floor, deadly radioactive floor,
# pickup CBRN protective clothing.
ED_SPECIAL_CRUMBLE = 230
ED_SPECIAL_RADIOACTIVE = 231
ED_SPECIAL_CBRN = 232
TOOLBAR_H = 120
TOPBAR_H = 50
# Heights of the two rows inside the toolbar (tools on top, actions on bottom).
TOOLBAR_ROW_TOOLS_H = 58
TOOLBAR_ROW_ACTIONS_H = 50


class EditorView(arcade.View):
    def __init__(self, load_data: Optional[dict] = None):
        super().__init__()
        self.grid_rows = 13
        self.grid_cols = 21
        self._init_grid()
        self.selected_tool = 1  # wall
        # Extended tools: which group/color is active for slab/laser and
        # for key/gate. User cycles with number keys or click-cycle.
        self.selected_group = 0   # 0..NUM_LASER_GROUPS-1 for slab/laser
        self.selected_color = 0   # 0..NUM_KEY_COLORS-1 for key/gate
        self.selected_box_color = 0  # 0..NUM_BOX_COLORS-1 for colored box/target
        self.cursor_r = 0
        self.cursor_c = 0
        # Raw mouse coords, updated in on_mouse_motion — used for tooltips
        self.hover_x = -1
        self.hover_y = -1
        self.hex_size = 0.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.background_color = C_BG
        self.message = ""
        self.msg_time = 0.0
        self.mouse_down = False
        # undo
        self.undo_stack: list[tuple] = []
        self.max_undo = 100
        # text input
        self.text_input_active = False
        self.text_input_value = ""
        self.text_input_prompt = ""
        self.text_input_callback = None
        # level name
        self.level_name = "Untitled"
        # import
        self.import_mode = False
        self.import_files: list = []
        self.import_selected = 0
        # help & analysis
        self.show_editor_help = False
        self.difficulty_text = ""
        self._last_solution = None
        # load
        if load_data:
            self._load_level_data(load_data)
            log(f"Editor: loaded '{load_data.get('name', '?')}'")
        else:
            log(f"Editor: new {self.grid_cols}x{self.grid_rows} grid")

    def _load_level_data(self, data: dict):
        """Load level data via the engine, which handles all extended tiles
        (colored boxes, colored targets, portals, etc.) uniformly."""
        lines = data.get("data", [])
        self.level_name = data.get("name", "Imported")
        if not lines:
            return
        eng = HexobanEngine()
        eng.load_from_lines(lines)
        self.grid_rows = eng.rows
        self.grid_cols = eng.cols
        self.grid = [row[:] for row in eng.grid]
        # Player position: only if the source actually had an @ or + glyph
        if any("@" in l or "+" in l for l in lines):
            self.player_pos = (eng.player_r, eng.player_c)
        else:
            self.player_pos = None
        self.boxes = set(eng.boxes)
        self.box_colors = dict(eng.box_colors)
        self.cursor_r = 0
        self.cursor_c = 0
        self.undo_stack.clear()

    def _init_grid(self):
        """Create a new grid surrounded by walls, interior floor."""
        self.grid = []
        for r in range(self.grid_rows):
            row = []
            for c in range(self.grid_cols):
                if r == 0 or r == self.grid_rows - 1 or c == 0 or c == self.grid_cols - 1:
                    row.append(WALL)
                else:
                    row.append(FLOOR)
            self.grid.append(row)
        self.player_pos: Optional[tuple[int, int]] = None
        self.boxes: set[tuple[int, int]] = set()
        # Parallel to self.boxes: maps position -> color for colored boxes.
        # Positions NOT present here are uncolored (classic '$') boxes.
        self.box_colors: dict = {}

    def _snapshot(self):
        return (
            [row[:] for row in self.grid],
            self.player_pos,
            set(self.boxes),
            dict(self.box_colors),
        )

    def _push_undo(self):
        self.undo_stack.append(self._snapshot())
        if len(self.undo_stack) > self.max_undo:
            self.undo_stack.pop(0)

    def _pop_undo(self):
        if not self.undo_stack:
            return
        snap = self.undo_stack.pop()
        # Backward-compatible unpack: older 3-tuple snapshots exist if a
        # saved editor state from the previous version is in memory.
        if len(snap) == 4:
            g, p, b, bc = snap
            self.box_colors = bc
        else:
            g, p, b = snap
            self.box_colors = {}
        self.grid = g
        self.player_pos = p
        self.boxes = b

    def on_show_view(self):
        self.background_color = C_BG
        self._calc_layout()

    def on_resize(self, w, h):
        super().on_resize(w, h)
        self._calc_layout()

    def _calc_layout(self):
        w, h = self.window.width, self.window.height
        avail_h = h - TOPBAR_H - TOOLBAR_H
        hex_w = math.sqrt(3)
        hex_h = 1.5

        grid_w_units = self.grid_cols * hex_w + (hex_w / 2 if self.grid_rows > 1 else 0)
        grid_h_units = (self.grid_rows - 1) * hex_h + 2

        max_s_w = (w - 40) / grid_w_units if grid_w_units > 0 else 30
        max_s_h = (avail_h - 20) / grid_h_units if grid_h_units > 0 else 30
        self.hex_size = min(max_s_w, max_s_h, 36)

        actual_w = grid_w_units * self.hex_size
        actual_h = grid_h_units * self.hex_size
        self.offset_x = (w - actual_w) / 2 + self.hex_size * math.sqrt(3) / 2
        self.offset_y = (avail_h - actual_h) / 2 + self.hex_size

    def _cell_center(self, r, c):
        s = self.hex_size
        hx, hy = hex_center(r, c, s)
        w, h = self.window.width, self.window.height
        x = self.offset_x + hx
        y = h - TOPBAR_H - self.offset_y - hy
        return x, y

    def _screen_to_cell(self, sx, sy):
        """Find the hex cell closest to screen point (sx, sy)."""
        best_r, best_c = None, None
        best_dist = float('inf')
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                cx, cy = self._cell_center(r, c)
                dist = math.hypot(sx - cx, sy - cy)
                if dist < best_dist and dist < self.hex_size * 1.1:
                    best_dist = dist
                    best_r, best_c = r, c
        return best_r, best_c

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        s = self.hex_size

        # top bar
        arcade.draw_rect_filled(XYWH(w / 2, h - TOPBAR_H / 2, w, TOPBAR_H), C_HUD_BAR)
        arcade.Text(f"\u270e {self.level_name}", 12, h - TOPBAR_H / 2, C_TITLE, 18,
                    anchor_y="center", bold=True).draw()
        # Resolve display name from the shared tool list
        tool_name = "?"
        for code, name, _col in self._all_editor_tools():
            if code == self.selected_tool:
                tool_name = name
                break
        arcade.Text(f"Tool: {tool_name}   Grid: {self.grid_cols}\u00d7{self.grid_rows}",
                    w / 2, h - TOPBAR_H / 2, C_HUD, 14,
                    anchor_x="center", anchor_y="center").draw()
        # Show difficulty rating if analyzed
        diff_info = f"  |  {self.difficulty_text}" if self.difficulty_text else ""
        arcade.Text(f"Undo: {len(self.undo_stack)}{diff_info}", w - 14, h - TOPBAR_H / 2,
                    C_HINT, 12, anchor_x="right", anchor_y="center").draw()

        # hex grid
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                cx, cy = self._cell_center(r, c)
                _draw_tile(cx, cy, s, self.grid[r][c])
                if (r, c) in self.boxes:
                    tid = self.grid[r][c]
                    on_target = (tid == TARGET or is_colored_target(tid))
                    color = self.box_colors.get((r, c), -1)
                    _draw_box(cx, cy, s, on_target, color=color)
                if self.player_pos == (r, c):
                    _draw_player(cx, cy, s)

        # cursor
        if 0 <= self.cursor_r < self.grid_rows and 0 <= self.cursor_c < self.grid_cols:
            cx, cy = self._cell_center(self.cursor_r, self.cursor_c)
            _draw_hex_outline(cx, cy, s, C_CURSOR, 3)

        # toolbar
        self._draw_toolbar(w, h)

        # message
        if self.message and time.time() - self.msg_time < 8:
            arcade.Text(self.message, w / 2, TOOLBAR_H + 16, C_SUCCESS, 15,
                        anchor_x="center").draw()

        # text input overlay
        if self.text_input_active:
            self._draw_text_input(w, h)

        # import overlay
        if self.import_mode:
            self._draw_import_overlay(w, h)

        # editor help overlay
        if self.show_editor_help:
            self._draw_editor_help(w, h)

    def _draw_text_input(self, w, h):
        bw, bh = 460, 130
        arcade.draw_rect_filled(XYWH(w/2, h/2, bw, bh), (25, 25, 40, 240))
        arcade.draw_rect_outline(XYWH(w/2, h/2, bw, bh), C_TITLE, 2)
        arcade.Text(self.text_input_prompt, w/2, h/2 + 35, C_TITLE, 18,
                    anchor_x="center", bold=True).draw()
        arcade.draw_rect_filled(XYWH(w/2, h/2 - 5, 380, 32), (40, 40, 55))
        arcade.draw_rect_outline(XYWH(w/2, h/2 - 5, 380, 32), C_MENU_SEL, 1)
        display_text = self.text_input_value + "\u2588"
        arcade.Text(display_text, w/2 - 180, h/2 - 5, C_MENU_SEL, 16,
                    anchor_y="center").draw()
        arcade.Text("Enter=Confirm  Esc=Cancel", w/2, h/2 - 42, C_HINT, 11,
                    anchor_x="center").draw()

    def _import_items(self):
        """Return combined list of (label, source) for import picker."""
        items = []
        for f in getattr(self, 'import_files', []):
            items.append((f"✉ {f.stem}", ("file", f)))
        for i, lv in enumerate(getattr(self, 'import_builtins', [])):
            items.append((f"⬢ {lv['name']}", ("builtin", i)))
        return items

    def _draw_import_overlay(self, w, h):
        items = self._import_items()
        bw = 520
        vis_count = min(len(items), 12) if items else 1
        bh = max(160, 90 + vis_count * 34)
        arcade.draw_rect_filled(XYWH(w/2, h/2, bw, bh), (25, 25, 40, 240))
        arcade.draw_rect_outline(XYWH(w/2, h/2, bw, bh), C_TITLE, 2)
        arcade.Text("Import Level", w/2, h/2 + bh/2 - 25, C_TITLE, 18,
                    anchor_x="center", bold=True).draw()
        if not items:
            arcade.Text("No levels available", w/2, h/2,
                        C_MENU, 15, anchor_x="center").draw()
        else:
            # Scrollable view
            scroll = max(0, self.import_selected - vis_count + 1)
            start_y = h/2 + bh/2 - 65
            for vi in range(vis_count):
                idx = scroll + vi
                if idx >= len(items):
                    break
                label, _ = items[idx]
                iy = start_y - vi * 34
                is_sel = idx == self.import_selected
                if is_sel:
                    arcade.draw_rect_filled(XYWH(w/2, iy, bw - 40, 30), C_SEL_BAR)
                col = C_MENU_SEL if is_sel else C_MENU
                arcade.Text(label, w/2, iy, col, 14,
                            anchor_x="center", anchor_y="center", bold=is_sel).draw()
        arcade.Text("\u2191/\u2193 Select \u2022 Enter Load \u2022 Esc Cancel",
                    w/2, h/2 - bh/2 + 15, C_HINT, 11, anchor_x="center").draw()

    def _all_editor_tools(self):
        """Return the ordered list of (tool_code, label, preview_color).

        tool_code is either an index into ED_TOOLS (int 0..3) or one of the
        ED_SPECIAL_* constants. This is the single source of truth — used
        by both toolbar rendering and toolbar hit-testing.
        """
        tools = []
        # Base tools (void/wall/floor/target) keyed by their index in ED_TOOLS
        for i, (_tid, name, col) in enumerate(ED_TOOLS):
            tools.append((i, name, col))
        tools.append((ED_SPECIAL_PLAYER, "Player", C_PLAYER))
        tools.append((ED_SPECIAL_BOX, "Box", C_BOX))
        tools.append((ED_SPECIAL_SLAB, f"Slab-{self.selected_group + 1}",
                      LASER_GROUP_COLORS[self.selected_group]))
        tools.append((ED_SPECIAL_LASER, f"Laser-{self.selected_group + 1}",
                      LASER_GROUP_COLORS[self.selected_group]))
        tools.append((ED_SPECIAL_KEY, f"Key-{self.selected_color + 1}",
                      KEY_COLORS[self.selected_color]))
        tools.append((ED_SPECIAL_GATE, f"Gate-{self.selected_color + 1}",
                      GATE_COLORS[self.selected_color]))
        # v3 tools — single instance of each; portal pair is single
        tools.append((ED_SPECIAL_PORTAL_IN, "Portal-In", C_PORTAL_IN))
        tools.append((ED_SPECIAL_PORTAL_OUT, "Portal-Out", C_PORTAL_OUT))
        tools.append((ED_SPECIAL_SWITCH, "Switch", C_SWITCH_ON))
        tools.append((ED_SPECIAL_COLORED_TARGET,
                      f"Tgt-C{self.selected_box_color + 1}",
                      BOX_COLOR_PALETTE[self.selected_box_color]))
        tools.append((ED_SPECIAL_COLORED_BOX,
                      f"Box-C{self.selected_box_color + 1}",
                      BOX_COLOR_PALETTE[self.selected_box_color]))
        # v4: crumble (single-use), radioactive (deadly), CBRN (pickup)
        tools.append((ED_SPECIAL_CRUMBLE, "Crumble", (140, 115, 85)))
        tools.append((ED_SPECIAL_RADIOACTIVE, "Radioactive", (255, 220, 30)))
        tools.append((ED_SPECIAL_CBRN, "CBRN", (210, 230, 60)))
        return tools

    def _draw_toolbar(self, w, h):
        """Two-row toolbar: tile tools on top, action buttons on bottom.
        Both rows are centered horizontally and never overlap."""
        arcade.draw_rect_filled(XYWH(w / 2, TOOLBAR_H / 2, w, TOOLBAR_H), C_HUD_BAR)
        # Row positions (y-center of each row)
        tools_row_y = TOOLBAR_ROW_ACTIONS_H + TOOLBAR_ROW_TOOLS_H / 2 + 4
        actions_row_y = TOOLBAR_ROW_ACTIONS_H / 2 + 2

        # ── Tool row ──
        tools = self._all_editor_tools()
        btn_w, gap = 54, 4
        total_w = len(tools) * btn_w + (len(tools) - 1) * gap
        # If even at btn_w=54 we overflow the window, shrink proportionally
        if total_w > w - 40:
            btn_w = max(28, int((w - 40 - (len(tools) - 1) * gap) / len(tools)))
            total_w = len(tools) * btn_w + (len(tools) - 1) * gap
        start_x = (w - total_w) / 2
        for i, (code, name, col) in enumerate(tools):
            bx = start_x + i * (btn_w + gap) + btn_w / 2
            is_sel = (self.selected_tool == code)
            bg = C_BTN_HOVER if is_sel else C_BTN
            arcade.draw_rect_filled(XYWH(bx, tools_row_y, btn_w, TOOLBAR_ROW_TOOLS_H - 4), bg)
            if is_sel:
                arcade.draw_rect_outline(
                    XYWH(bx, tools_row_y, btn_w, TOOLBAR_ROW_TOOLS_H - 4), C_TITLE, 2)
            _draw_hex_filled(bx, tools_row_y + 10, 9, col)
            arcade.Text(name, bx, tools_row_y - 15,
                        C_MENU_SEL if is_sel else C_MENU, 8,
                        anchor_x="center", anchor_y="center").draw()
            shortcut = str(i + 1) if i < 10 else ""
            if shortcut:
                # Shortcuts 1..10 map to keys 1..9 then 0; display accordingly
                display = shortcut if shortcut != "10" else "0"
                arcade.Text(display, bx + btn_w / 2 - 4, tools_row_y + 22,
                            C_HINT, 8, anchor_x="right").draw()

        # ── Action row ──
        actions = self._get_actions()
        abtn_w, agap = 56, 4
        atotal_w = len(actions) * abtn_w + (len(actions) - 1) * agap
        if atotal_w > w - 40:
            abtn_w = max(30, int((w - 40 - (len(actions) - 1) * agap) / len(actions)))
            atotal_w = len(actions) * abtn_w + (len(actions) - 1) * agap
        astart_x = (w - atotal_w) / 2
        for i, (label, key_hint) in enumerate(actions):
            ax = astart_x + i * (abtn_w + agap) + abtn_w / 2
            arcade.draw_rect_filled(
                XYWH(ax, actions_row_y, abtn_w, TOOLBAR_ROW_ACTIONS_H - 6), C_BTN)
            arcade.draw_rect_outline(
                XYWH(ax, actions_row_y, abtn_w, TOOLBAR_ROW_ACTIONS_H - 6),
                C_BTN_BORDER, 1)
            arcade.Text(label, ax, actions_row_y + 5, C_MENU, 9,
                        anchor_x="center", anchor_y="center").draw()
            arcade.Text(key_hint, ax, actions_row_y - 10, C_HINT, 8,
                        anchor_x="center", anchor_y="center").draw()

        # Hover tooltip — drawn last so it sits on top of everything
        self._draw_tooltip_if_hover(w, h)

    def _tool_button_rect(self, i, n_tools, w):
        """Return (bx, by, btn_w, btn_h) for tool button i. Mirrors layout
        in _draw_toolbar — keep this in sync."""
        btn_w, gap = 54, 4
        total_w = n_tools * btn_w + (n_tools - 1) * gap
        if total_w > w - 40:
            btn_w = max(28, int((w - 40 - (n_tools - 1) * gap) / n_tools))
            total_w = n_tools * btn_w + (n_tools - 1) * gap
        start_x = (w - total_w) / 2
        bx = start_x + i * (btn_w + gap) + btn_w / 2
        by = TOOLBAR_ROW_ACTIONS_H + TOOLBAR_ROW_TOOLS_H / 2 + 4
        return bx, by, btn_w, TOOLBAR_ROW_TOOLS_H - 4

    def _action_button_rect(self, i, n_actions, w):
        """Return (ax, ay, abtn_w, abtn_h) for action button i."""
        abtn_w, agap = 56, 4
        atotal_w = n_actions * abtn_w + (n_actions - 1) * agap
        if atotal_w > w - 40:
            abtn_w = max(30, int((w - 40 - (n_actions - 1) * agap) / n_actions))
            atotal_w = n_actions * abtn_w + (n_actions - 1) * agap
        astart_x = (w - atotal_w) / 2
        ax = astart_x + i * (abtn_w + agap) + abtn_w / 2
        ay = TOOLBAR_ROW_ACTIONS_H / 2 + 2
        return ax, ay, abtn_w, TOOLBAR_ROW_ACTIONS_H - 6

    # Tooltip texts — keyed by tool code for tools, by label for actions.
    # Deliberately written to explain *mechanics*, not just restate the name,
    # since the name is already visible on the button.
    _TOOL_TOOLTIPS = {
        ED_SPECIAL_PLAYER: "Place the player (only one per level).",
        ED_SPECIAL_BOX: "Common box. Any common target satisfies it.",
        ED_SPECIAL_SLAB:
            "Pressure plate. Disarms linked lasers while player or box stands on it.",
        ED_SPECIAL_LASER:
            "Deadly laser beam. Blocks movement until a slab of the same group is pressed.",
        ED_SPECIAL_KEY:
            "Key. Picked up by the player; consumed to open a gate of the same color.",
        ED_SPECIAL_GATE:
            "Gate. Blocks until the player has a matching-color key; opens permanently.",
        ED_SPECIAL_PORTAL_IN:
            "Blue portal (entry). Teleports player to orange portal when switch is ON.",
        ED_SPECIAL_PORTAL_OUT:
            "Orange portal (destination). Receiving end of teleport; cannot enter to teleport.",
        ED_SPECIAL_SWITCH:
            "Electrical switch. Step on to toggle; portal works only when ON.",
        ED_SPECIAL_COLORED_TARGET:
            "Colored target. Only a box of the same color completes it.",
        ED_SPECIAL_COLORED_BOX:
            "Colored box. Must be pushed onto a matching-color target.",
        ED_SPECIAL_CRUMBLE:
            "Crumble floor. Collapses into void after the player leaves — "
            "single-use tile, pick your route carefully.",
        ED_SPECIAL_RADIOACTIVE:
            "Radioactive floor. Deadly on entry unless the player has "
            "picked up CBRN protective clothing.",
        ED_SPECIAL_CBRN:
            "CBRN protective clothing. Picked up on entry; "
            "lets the player walk on radioactive tiles for the rest of the level.",
    }
    _ACTION_TOOLTIPS = {
        "Name": "Rename the level (also used as save filename).",
        "Save": "Save the level to levels/ as JSON.",
        "Import": "Load an existing level or built-in to edit.",
        "Export": "Save under a new name (save-as).",
        "Test": "Switch to play mode for this level.",
        "Solve": "Run the auto-solver and report moves/pushes.",
        "Analyze": "Estimate difficulty from BFS states.",
        "Walls": "Auto-seal exposed floor edges with walls.",
        "Clear": "Reset the grid (walls on border, floor inside).",
        "Size": "Set grid dimensions as WxH (e.g. 10x8).",
        "R+": "Add a row.",
        "R-": "Remove a row.",
        "C+": "Add a column.",
        "C-": "Remove a column.",
        "Undo": "Revert last paint or resize.",
        "Help": "Show editor keyboard reference.",
        "Back": "Return to main menu.",
    }

    def _draw_tooltip_if_hover(self, w, h):
        """If the mouse is hovering over a toolbar button, draw a tooltip
        bubble directly above the toolbar pointing at the button."""
        if self.hover_x < 0 or self.hover_y < 0:
            return
        # Only bother if the mouse is in the toolbar band
        if self.hover_y > TOOLBAR_H + 4:
            return

        text = None
        anchor_x = None

        # Check tool buttons first (they're the top row)
        tools = self._all_editor_tools()
        for i, (code, _name, _col) in enumerate(tools):
            bx, by, bw, bh = self._tool_button_rect(i, len(tools), w)
            if abs(self.hover_x - bx) < bw / 2 and abs(self.hover_y - by) < bh / 2:
                text = self._TOOL_TOOLTIPS.get(code)
                anchor_x = bx
                break
        if text is None:
            actions = self._get_actions()
            for i, (label, _k) in enumerate(actions):
                ax, ay, abw, abh = self._action_button_rect(i, len(actions), w)
                if abs(self.hover_x - ax) < abw / 2 and abs(self.hover_y - ay) < abh / 2:
                    text = self._ACTION_TOOLTIPS.get(label)
                    anchor_x = ax
                    break
        if not text:
            return

        # Draw a pill at y = TOOLBAR_H + padding, centered horizontally on
        # the button when possible, nudged inward if it would clip the window.
        tw = max(120, min(520, 7 * len(text)))   # rough width for 11-pt text
        th = 28
        ty = TOOLBAR_H + 18
        tx = anchor_x
        if tx - tw / 2 < 8:
            tx = 8 + tw / 2
        if tx + tw / 2 > w - 8:
            tx = w - 8 - tw / 2
        arcade.draw_rect_filled(XYWH(tx, ty, tw, th), (30, 30, 45, 240))
        arcade.draw_rect_outline(XYWH(tx, ty, tw, th), C_TITLE, 1)
        arcade.Text(text, tx, ty, C_MENU_SEL, 11,
                    anchor_x="center", anchor_y="center").draw()

    def _paint_at(self, r, c):
        if r is None or c is None:
            return
        tool = self.selected_tool
        if tool == ED_SPECIAL_PLAYER:
            if self.player_pos != (r, c):
                self._push_undo()
                self.player_pos = (r, c)
                self.boxes.discard((r, c))
                self.box_colors.pop((r, c), None)
        elif tool == ED_SPECIAL_BOX:
            self._push_undo()
            pos = (r, c)
            if pos in self.boxes:
                # Toggle off any box (colored or not)
                self.boxes.discard(pos)
                self.box_colors.pop(pos, None)
            else:
                self.boxes.add(pos)
                # Uncolored box — ensure no stale color entry
                self.box_colors.pop(pos, None)
                if self.player_pos == pos:
                    self.player_pos = None
        elif tool == ED_SPECIAL_COLORED_BOX:
            # Place a colored box of the currently selected box color.
            # Clicking on an existing matching-color box removes it.
            self._push_undo()
            pos = (r, c)
            if pos in self.boxes and self.box_colors.get(pos) == self.selected_box_color:
                self.boxes.discard(pos)
                self.box_colors.pop(pos, None)
            else:
                self.boxes.add(pos)
                self.box_colors[pos] = self.selected_box_color
                if self.player_pos == pos:
                    self.player_pos = None
        elif tool == ED_SPECIAL_SLAB:
            self._paint_tid(r, c, slab_id(self.selected_group))
        elif tool == ED_SPECIAL_LASER:
            self._paint_tid(r, c, laser_id(self.selected_group))
        elif tool == ED_SPECIAL_KEY:
            self._paint_tid(r, c, key_id(self.selected_color))
        elif tool == ED_SPECIAL_GATE:
            self._paint_tid(r, c, gate_id(self.selected_color))
        elif tool == ED_SPECIAL_PORTAL_IN:
            self._paint_tid(r, c, PORTAL_IN)
        elif tool == ED_SPECIAL_PORTAL_OUT:
            self._paint_tid(r, c, PORTAL_OUT)
        elif tool == ED_SPECIAL_SWITCH:
            self._paint_tid(r, c, SWITCH)
        elif tool == ED_SPECIAL_COLORED_TARGET:
            self._paint_tid(r, c, colored_target_id(self.selected_box_color))
        elif tool == ED_SPECIAL_CRUMBLE:
            self._paint_tid(r, c, CRUMBLE)
        elif tool == ED_SPECIAL_RADIOACTIVE:
            self._paint_tid(r, c, RADIOACTIVE)
        elif tool == ED_SPECIAL_CBRN:
            self._paint_tid(r, c, CBRN_ITEM)
        else:
            tid = ED_TOOLS[tool][0]
            self._paint_tid(r, c, tid)

    def _paint_tid(self, r, c, tid):
        """Paint a specific tile id at (r, c), clearing player/box if wall/void."""
        if self.grid[r][c] == tid:
            return
        self._push_undo()
        self.grid[r][c] = tid
        if tid in (WALL, EMPTY):
            self.boxes.discard((r, c))
            self.box_colors.pop((r, c), None)
            if self.player_pos == (r, c):
                self.player_pos = None

    def _cycle_group_color(self, delta: int):
        """Cycle the slab/laser group, the key/gate color, or the colored-box/
        colored-target color based on the currently selected tool."""
        if self.selected_tool in (ED_SPECIAL_SLAB, ED_SPECIAL_LASER):
            self.selected_group = (self.selected_group + delta) % NUM_LASER_GROUPS
            self._msg(f"Laser group: {self.selected_group + 1}")
        elif self.selected_tool in (ED_SPECIAL_KEY, ED_SPECIAL_GATE):
            self.selected_color = (self.selected_color + delta) % NUM_KEY_COLORS
            self._msg(f"Key color: {self.selected_color + 1}")
        elif self.selected_tool in (ED_SPECIAL_COLORED_TARGET, ED_SPECIAL_COLORED_BOX):
            self.selected_box_color = (self.selected_box_color + delta) % NUM_BOX_COLORS
            self._msg(f"Box color: {self.selected_box_color + 1}")

    def on_mouse_press(self, x, y, button, mods):
        if button == arcade.MOUSE_BUTTON_LEFT:
            if y < TOOLBAR_H + 4:
                clicked_tool = self._toolbar_hit(x, y)
                if clicked_tool is not None:
                    if clicked_tool >= 0:  # -1 means action button handled
                        self.selected_tool = clicked_tool
                    return
            r, c = self._screen_to_cell(x, y)
            if r is not None:
                self.cursor_r, self.cursor_c = r, c
                self._paint_at(r, c)
                self.mouse_down = True

    def _toolbar_hit(self, mx, my):
        w = self.window.width
        tools = self._all_editor_tools()
        for i, (code, _name, _col) in enumerate(tools):
            bx, by, bw, bh = self._tool_button_rect(i, len(tools), w)
            if abs(mx - bx) < bw / 2 and abs(my - by) < bh / 2:
                return code
        # Check action buttons
        action_hit = self._action_hit(mx, my)
        if action_hit is not None:
            self._run_action(action_hit)
            return -1  # signal: action handled, don't change tool
        return None

    def _action_hit(self, mx, my):
        """Return action index if mouse hit an action button, else None."""
        w = self.window.width
        actions = self._get_actions()
        for i in range(len(actions)):
            ax, ay, abw, abh = self._action_button_rect(i, len(actions), w)
            if abs(mx - ax) < abw / 2 and abs(my - ay) < abh / 2:
                return i
        return None

    def _get_actions(self):
        return [
            ("Name", "N"), ("Save", "S"), ("Import", "I"), ("Export", "E"),
            ("Test", "T"), ("Solve", "V"), ("Analyze", "G"),
            ("Walls", "F"), ("Clear", "C"), ("Size", "W"),
            ("R+", "]"), ("R-", "["), ("C+", "="), ("C-", "-"),
            ("Undo", "Z"), ("Help", "H"), ("Back", "Esc"),
        ]

    def _run_action(self, idx):
        """Execute action by index from the toolbar."""
        actions = self._get_actions()
        if idx < 0 or idx >= len(actions):
            return
        label = actions[idx][0]
        action_map = {
            "Name": self._start_name_input,
            "Save": self._save,
            "Import": self._start_import,
            "Export": self._export,
            "Test": self._test,
            "Solve": self._solve_current,
            "Analyze": self._analyze,
            "Walls": self._auto_walls,
            "Clear": self._clear,
            "Size": self._start_size_input,
            "R+": lambda: self._resize_grid(1, 0),
            "R-": lambda: self._resize_grid(-1, 0),
            "C+": lambda: self._resize_grid(0, 1),
            "C-": lambda: self._resize_grid(0, -1),
            "Undo": self._pop_undo,
            "Help": lambda: setattr(self, 'show_editor_help', True),
            "Back": lambda: self.window.show_view(MenuView()),
        }
        fn = action_map.get(label)
        if fn:
            fn()

    def on_mouse_release(self, x, y, button, mods):
        if button == arcade.MOUSE_BUTTON_LEFT:
            self.mouse_down = False

    def on_mouse_drag(self, x, y, dx, dy, buttons, mods):
        if self.mouse_down:
            r, c = self._screen_to_cell(x, y)
            if r is not None and (r, c) != (self.cursor_r, self.cursor_c):
                self.cursor_r, self.cursor_c = r, c
                if self.selected_tool < len(ED_TOOLS):
                    self._paint_at(r, c)

    def on_mouse_motion(self, x, y, dx, dy):
        # Track raw mouse pos for toolbar tooltips
        self.hover_x, self.hover_y = x, y
        r, c = self._screen_to_cell(x, y)
        if r is not None:
            self.cursor_r, self.cursor_c = r, c

    def on_key_press(self, key, mods):
        # text input mode
        if self.text_input_active:
            if key == arcade.key.ESCAPE:
                self.text_input_active = False
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                cb = self.text_input_callback
                val = self.text_input_value.strip()
                self.text_input_active = False
                if cb and val:
                    cb(val)
            elif key == arcade.key.BACKSPACE:
                self.text_input_value = self.text_input_value[:-1]
            return

        # import picker
        if self.import_mode:
            items = self._import_items()
            if key == arcade.key.ESCAPE:
                self.import_mode = False
            elif _is_nav_up(key):
                if items:
                    self.import_selected = (self.import_selected - 1) % len(items)
            elif _is_nav_down(key):
                if items:
                    self.import_selected = (self.import_selected + 1) % len(items)
            elif key in (arcade.key.RETURN, arcade.key.ENTER):
                if items and 0 <= self.import_selected < len(items):
                    _, source = items[self.import_selected]
                    if source[0] == "file":
                        self._do_import(source[1])
                    elif source[0] == "builtin":
                        self._do_import_builtin(source[1])
                self.import_mode = False
            return

        # help overlay dismiss
        if self.show_editor_help:
            self.show_editor_help = False
            return

        keys = self.window.keys
        # arrow cursor
        if key == arcade.key.UP:
            self.cursor_r = max(0, self.cursor_r - 1)
        elif key == arcade.key.DOWN:
            self.cursor_r = min(self.grid_rows - 1, self.cursor_r + 1)
        elif key == arcade.key.LEFT:
            self.cursor_c = max(0, self.cursor_c - 1)
        elif key == arcade.key.RIGHT:
            self.cursor_c = min(self.grid_cols - 1, self.cursor_c + 1)
        elif key in (arcade.key.RETURN, arcade.key.ENTER, arcade.key.SPACE):
            self._paint_at(self.cursor_r, self.cursor_c)
        # tool shortcuts 1-6
        elif key == arcade.key.KEY_1: self.selected_tool = 0
        elif key == arcade.key.KEY_2: self.selected_tool = 1
        elif key == arcade.key.KEY_3: self.selected_tool = 2
        elif key == arcade.key.KEY_4: self.selected_tool = 3
        elif key == arcade.key.KEY_5: self.selected_tool = ED_SPECIAL_PLAYER
        elif key == arcade.key.KEY_6: self.selected_tool = ED_SPECIAL_BOX
        # New tool shortcuts 7-0
        elif key == arcade.key.KEY_7: self.selected_tool = ED_SPECIAL_SLAB
        elif key == arcade.key.KEY_8: self.selected_tool = ED_SPECIAL_LASER
        elif key == arcade.key.KEY_9: self.selected_tool = ED_SPECIAL_KEY
        elif key == arcade.key.KEY_0: self.selected_tool = ED_SPECIAL_GATE
        elif key == arcade.key.P: self.selected_tool = ED_SPECIAL_PLAYER
        elif key == arcade.key.B: self.selected_tool = ED_SPECIAL_BOX
        # Cycle group (for slab/laser) or color (for key/gate) with , / .
        elif key == arcade.key.COMMA:
            self._cycle_group_color(-1)
        elif key == arcade.key.PERIOD:
            self._cycle_group_color(+1)
        elif key == arcade.key.TAB:
            tools = [code for code, _n, _c in self._all_editor_tools()]
            idx = tools.index(self.selected_tool) if self.selected_tool in tools else 0
            self.selected_tool = tools[(idx + 1) % len(tools)]
        # grid resize
        elif key == arcade.key.BRACKETRIGHT:
            self._resize_grid(1, 0)
        elif key == arcade.key.BRACKETLEFT:
            self._resize_grid(-1, 0)
        elif key == arcade.key.EQUAL:
            self._resize_grid(0, 1)
        elif key == arcade.key.MINUS:
            self._resize_grid(0, -1)
        # undo
        elif key == arcade.key.Z:
            self._pop_undo()
        # actions
        elif key == arcade.key.N:
            self._start_name_input()
        elif key == arcade.key.S:
            self._save()
        elif key == arcade.key.I:
            self._start_import()
        elif key == arcade.key.E:
            self._export()
        elif key == arcade.key.T:
            self._test()
        elif key == arcade.key.C:
            self._clear()
        elif key == arcade.key.V:
            self._solve_current()
        elif key == arcade.key.G:
            self._analyze()
        elif key == arcade.key.W:
            self._start_size_input()
        elif key == arcade.key.H:
            self.show_editor_help = not self.show_editor_help
        elif key == arcade.key.F:
            self._auto_walls()
        elif key == arcade.key.ESCAPE:
            if self.show_editor_help:
                self.show_editor_help = False
            else:
                self.window.show_view(MenuView())
        elif key == keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)
            self._calc_layout()

    def _resize_grid(self, dr, dc):
        nr = max(4, min(30, self.grid_rows + dr))
        nc = max(4, min(30, self.grid_cols + dc))
        if nr == self.grid_rows and nc == self.grid_cols:
            return
        self._push_undo()
        new_grid = []
        for r in range(nr):
            row = []
            for c in range(nc):
                if r < self.grid_rows and c < self.grid_cols:
                    row.append(self.grid[r][c])
                elif r == 0 or r == nr - 1 or c == 0 or c == nc - 1:
                    row.append(WALL)
                else:
                    row.append(FLOOR)
            new_grid.append(row)
        self.grid = new_grid
        self.grid_rows = nr
        self.grid_cols = nc
        self.boxes = {(r, c) for r, c in self.boxes if r < nr and c < nc}
        if self.player_pos and (self.player_pos[0] >= nr or self.player_pos[1] >= nc):
            self.player_pos = None
        self.cursor_r = min(self.cursor_r, nr - 1)
        self.cursor_c = min(self.cursor_c, nc - 1)
        self._calc_layout()
        self._msg(f"Grid: {nc}\u00d7{nr}")

    def _msg(self, text):
        self.message = text
        self.msg_time = time.time()

    def _to_xsb(self, require_player=True):
        if require_player and not self.player_pos:
            self._msg("Place a player first! (key 5 or P)")
            return None
        # Build a boxes dict so colored boxes serialize with their colors.
        # Uncolored boxes map to -1 (which grid_to_xsb treats as classic).
        boxes_arg = {pos: self.box_colors.get(pos, -1) for pos in self.boxes}
        return grid_to_xsb(self.grid,
                           self.player_pos[0] if self.player_pos else 0,
                           self.player_pos[1] if self.player_pos else 0,
                           boxes_arg)

    def _validate_level(self) -> str:
        """Check level integrity. Returns error message or empty string."""
        from src.levels import is_walkable_base as _walkable
        if not self.player_pos:
            return "No player placed"
        pr, pc = self.player_pos
        if not (0 <= pr < self.grid_rows and 0 <= pc < self.grid_cols):
            return f"Player out of bounds ({pr},{pc})"
        if not _walkable(self.grid[pr][pc]):
            return f"Player on non-walkable cell ({pr},{pc})"
        for br, bc in self.boxes:
            if not (0 <= br < self.grid_rows and 0 <= bc < self.grid_cols):
                return f"Box out of bounds ({br},{bc})"
            if not _walkable(self.grid[br][bc]):
                return f"Box on non-walkable cell ({br},{bc})"
        # Count all target-like cells (classic '.' + colored targets)
        targets_in_grid = set()
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                t = self.grid[r][c]
                if t == TARGET or is_colored_target(t):
                    targets_in_grid.add((r, c))
        if len(self.boxes) != len(targets_in_grid):
            return f"Mismatch: {len(self.boxes)} boxes vs {len(targets_in_grid)} targets"
        if len(self.boxes) == 0:
            return "No boxes or targets placed"
        # Fidelity check: export and re-import through the engine
        lines = self._to_xsb(require_player=False)
        if lines:
            eng = HexobanEngine()
            eng.load_from_lines(lines)
            if (eng.player_r, eng.player_c) != self.player_pos:
                return f"Fidelity: player pos changed on save"
            if eng.boxes != self.boxes:
                return f"Fidelity: boxes changed on save ({len(eng.boxes)} vs {len(self.boxes)})"
            if eng.targets != targets_in_grid:
                return f"Fidelity: targets changed on save"
            if eng.box_colors != self.box_colors:
                return f"Fidelity: box colors changed on save"
        return ""

    def on_text(self, text):
        if self.text_input_active:
            if text.isprintable() and len(self.text_input_value) < 40:
                self.text_input_value += text

    def _open_text_input(self, prompt, default, callback):
        self.text_input_prompt = prompt
        self.text_input_value = default
        self.text_input_callback = callback
        self.text_input_active = True

    def _start_name_input(self):
        self._open_text_input("Level Name:", self.level_name, self._finish_name)

    def _finish_name(self, name):
        self.level_name = name
        self._msg(f"Name set: {name}")

    def _save(self):
        # Validate before saving
        err = self._validate_level()
        if err:
            self._msg(f"\u274c {err}")
            log(f"Editor: save blocked — {err}")
            return
        lines = self._to_xsb()
        if not lines:
            return
        if self.level_name == "Untitled":
            self._open_text_input("Name your level before saving:", "", self._finish_save)
        else:
            self._do_save(self.level_name, lines)

    def _finish_save(self, name):
        self.level_name = name
        lines = self._to_xsb()
        if lines:
            self._do_save(name, lines)

    def _do_save(self, name, lines):
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        safe = safe.strip().replace(" ", "_") or f"custom_{int(time.time())}"
        path = f"levels/{safe}.json"
        save_level_file(path, name, lines)
        self._msg(f"Saved: {path}")
        log(f"Editor: saved '{name}' to {path}")

    def _export(self):
        lines = self._to_xsb()
        if not lines:
            return
        self._open_text_input("Export as (level name):", self.level_name, self._finish_export)

    def _finish_export(self, name):
        self.level_name = name
        lines = self._to_xsb()
        if lines:
            self._do_save(name, lines)

    def _start_import(self):
        self.import_files = list_saved_levels()
        # Also include builtin levels as importable items
        self.import_builtins = list(BUILTIN_LEVELS)
        self.import_selected = 0
        self.import_mode = True

    def _do_import(self, filepath):
        data = load_level_file(str(filepath))
        if data:
            self._load_level_data(data)
            self._calc_layout()
            self._msg(f"Imported: {data.get('name', filepath.stem)}")
        else:
            self._msg("Failed to load file")

    def _auto_walls(self):
        """Surround all floor/target cells with walls on empty/void neighbors.
        
        Flood-fill from all floor cells; any EMPTY/void cell adjacent to a 
        floor cell becomes a WALL. Also seal the grid border.
        """
        from src.levels import hex_neighbors as _hn
        self._push_undo()
        changed = 0
        # First: set all border cells to WALL if they are EMPTY
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if r == 0 or r == self.grid_rows - 1 or c == 0 or c == self.grid_cols - 1:
                    if self.grid[r][c] == EMPTY:
                        self.grid[r][c] = WALL
                        changed += 1
        # Then: any EMPTY cell adjacent to FLOOR/TARGET becomes WALL
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if self.grid[r][c] in (FLOOR, TARGET):
                    nbs = _hn(r, c)
                    for d, (nr, nc) in nbs.items():
                        if 0 <= nr < self.grid_rows and 0 <= nc < self.grid_cols:
                            if self.grid[nr][nc] == EMPTY:
                                self.grid[nr][nc] = WALL
                                changed += 1
                        # Out-of-bounds neighbor means floor is at edge
                        # — we can't add walls outside grid, but border is already handled
        # Also check that any floor cell touching grid boundary gets a wall
        for r in range(self.grid_rows):
            for c in range(self.grid_cols):
                if self.grid[r][c] in (FLOOR, TARGET):
                    nbs = _hn(r, c)
                    for d, (nr, nc) in nbs.items():
                        if not (0 <= nr < self.grid_rows and 0 <= nc < self.grid_cols):
                            # Neighbor is outside grid — this floor cell is at the edge
                            # Mark this cell as WALL to seal the boundary
                            # Actually better: expand grid or mark the floor cell.
                            # For now just flag it.
                            pass
        self._msg(f"Auto-walls: {changed} cells sealed" if changed else "Map already sealed")

    def _draw_editor_help(self, w, h):
        """Draw help overlay for the editor."""
        bw, bh = 560, 560
        arcade.draw_rect_filled(XYWH(w/2, h/2, bw, bh), (20, 20, 35, 235))
        arcade.draw_rect_outline(XYWH(w/2, h/2, bw, bh), C_TITLE, 2)
        lines = [
            ("EDITOR HELP", 22, C_TITLE, True),
            ("", 6, C_HUD, False),
            ("Click/drag on hex grid to paint tiles", 14, C_HUD, False),
            ("1=Void  2=Wall  3=Floor  4=Target  5=Player  6=Box", 13, C_HUD, False),
            ("7=Slab  8=Laser  9=Key  0=Gate", 13, C_HUD, False),
            (", / . = cycle slab/laser group or key/gate color", 13, C_HUD, False),
            ("Tab = cycle tools  |  Arrows = move cursor", 13, C_HUD, False),
            ("Enter/Space = paint at cursor", 13, C_HUD, False),
            ("", 6, C_HUD, False),
            ("N = Name level  |  S = Save  |  I = Import", 13, C_HUD, False),
            ("E = Export (save as)  |  T = Test play", 13, C_HUD, False),
            ("V = Solve (check solvability)", 13, C_HUD, False),
            ("G = Analyze (difficulty rating)", 13, C_HUD, False),
            ("F = Auto-walls (seal open edges)", 13, C_HUD, False),
            ("W = Set grid dimensions (e.g. 10x8)", 13, C_HUD, False),
            ("", 6, C_HUD, False),
            ("] = add row  |  [ = remove row", 13, C_HUD, False),
            ("= = add column  |  - = remove column", 13, C_HUD, False),
            ("Z = Undo  |  C = Clear grid", 13, C_HUD, False),
            ("", 6, C_HUD, False),
            ("Slab + Laser: same group disarms laser when slab pressed", 12, C_WARN, False),
            ("Key + Gate: same color; key consumed on opening gate", 12, C_WARN, False),
            ("Portal-In + Portal-Out + Switch: step switch to enable", 12, C_WARN, False),
            ("Colored Box matches Colored Target of same color", 12, C_WARN, False),
            ("Crumble: floor collapses after player leaves (single use)", 12, C_WARN, False),
            ("Radioactive: deadly unless player picked up CBRN suit", 12, C_WARN, False),
            ("", 6, C_HUD, False),
            ("H = Toggle this help  |  Esc = Back", 13, C_HINT, False),
        ]
        y = h / 2 + bh / 2 - 28
        for text, sz, col, bold in lines:
            if text:
                arcade.Text(text, w / 2, y, col, sz, anchor_x="center", bold=bold).draw()
            y -= sz + 6

    def _do_import_builtin(self, idx):
        """Import a builtin level into the editor."""
        lv = BUILTIN_LEVELS[idx]
        self._load_level_data(lv)
        self._calc_layout()
        self._msg(f"Imported: {lv['name']}")

    def _clear(self):
        self._push_undo()
        self._init_grid()
        self.level_name = "Untitled"
        self._msg("Grid cleared (walls on border)")

    def _start_size_input(self):
        """Open a text input to set grid dimensions as WxH."""
        self._open_text_input(
            f"Grid size (cols x rows), current {self.grid_cols}x{self.grid_rows}:",
            f"{self.grid_cols}x{self.grid_rows}",
            self._finish_size_input)

    def _finish_size_input(self, text):
        """Parse 'WxH' or 'W*H' and resize grid."""
        text = text.strip().lower()
        for sep in ['x', '*', ',', ' ']:
            if sep in text:
                parts = text.split(sep, 1)
                try:
                    nc = max(4, min(30, int(parts[0].strip())))
                    nr = max(4, min(30, int(parts[1].strip())))
                    dr = nr - self.grid_rows
                    dc = nc - self.grid_cols
                    if dr != 0 or dc != 0:
                        self._push_undo()
                        new_grid = []
                        for r in range(nr):
                            row = []
                            for c in range(nc):
                                if r < self.grid_rows and c < self.grid_cols:
                                    row.append(self.grid[r][c])
                                elif r == 0 or r == nr - 1 or c == 0 or c == nc - 1:
                                    row.append(WALL)
                                else:
                                    row.append(FLOOR)
                            self.grid.append(row) if False else None  # noqa
                            row_final = row
                            new_grid.append(row_final)
                        self.grid = new_grid
                        self.grid_rows = nr
                        self.grid_cols = nc
                        self.boxes = {(r, c) for r, c in self.boxes if r < nr and c < nc}
                        if self.player_pos and (self.player_pos[0] >= nr or self.player_pos[1] >= nc):
                            self.player_pos = None
                        self.cursor_r = min(self.cursor_r, nr - 1)
                        self.cursor_c = min(self.cursor_c, nc - 1)
                        self._calc_layout()
                    self._msg(f"Grid: {nc}\u00d7{nr}")
                    return
                except ValueError:
                    pass
        self._msg("Invalid format. Use: 10x8")

    def _solve_current(self):
        """Run the solver on the current editor level."""
        lines = self._to_xsb()
        if not lines:
            return
        from src.resolver import solve
        eng = HexobanEngine()
        eng.load_from_lines(lines)
        if len(eng.boxes) == 0:
            self._msg("Place at least one box and one target!")
            return
        if len(eng.boxes) != len(eng.targets):
            self._msg(f"Mismatch: {len(eng.boxes)} boxes, {len(eng.targets)} targets")
            return
        self._msg("Solving... please wait")
        result = solve(eng)
        if result:
            self._msg(f"\u2705 Solvable! {len(result)} moves, {eng.pushes} pushes")
            # Store solution to offer replay via Test
            self._last_solution = result
        else:
            self._msg("\u274c No solution found (too complex or unsolvable)")
            self._last_solution = None

    def _analyze(self):
        """Analyze the current level for difficulty metrics using A* solver."""
        lines = self._to_xsb()
        if not lines:
            return
        from src.resolver import solve, _solve_astar, _heuristic, hex_distance
        eng = HexobanEngine()
        eng.load_from_lines(lines)
        if len(eng.boxes) == 0 or len(eng.boxes) != len(eng.targets):
            self._msg(f"Need matching boxes/targets ({len(eng.boxes)}b {len(eng.targets)}t)")
            return

        self._msg("Analyzing (A* solver)...")
        floor_cells = sum(1 for r in range(eng.rows) for c in range(eng.cols)
                          if eng.grid[r][c] in (FLOOR, TARGET))
        n_boxes = len(eng.boxes)

        # Use the main solver (A* with heuristic + deadlock pruning)
        solution = solve(eng)

        if solution:
            n_moves = len(solution)
            n_pushes = sum(1 for d in solution
                          if True)  # count all moves; pushes need separate tracking
            # Re-run to count pushes precisely
            eng2 = HexobanEngine()
            eng2.load_from_lines(lines)
            push_count = 0
            for d in solution:
                old_boxes = frozenset(eng2.boxes)
                eng2.move(d)
                if frozenset(eng2.boxes) != old_boxes:
                    push_count += 1

            # Difficulty classification
            if n_moves <= 3 and n_boxes == 1:
                difficulty = "Tutorial"
            elif n_moves <= 6 and n_boxes <= 2:
                difficulty = "Easy"
            elif n_moves <= 15 and n_boxes <= 3:
                difficulty = "Medium"
            elif n_moves <= 30:
                difficulty = "Hard"
            elif n_moves <= 60:
                difficulty = "Very Hard"
            else:
                difficulty = "Extreme"

            # Refine by box count
            if n_boxes >= 4 and difficulty in ("Easy", "Medium"):
                difficulty = "Hard"

            msg = (f"\u2705 {difficulty} | {n_moves} moves, {push_count} pushes, "
                   f"{n_boxes} boxes | {floor_cells} floor cells")
            self.difficulty_text = f"{difficulty} ({n_moves}m {push_count}p)"
        else:
            msg = f"\u274c No solution (2M states) | {n_boxes} boxes, {floor_cells} floor"
            self.difficulty_text = "Unsolvable?"
        self._msg(msg)

    def _test(self):
        lines = self._to_xsb()
        if not lines:
            return
        self.window.show_view(GameView(lines, self.level_name, -1))


# ═══════════════════════════════════════════════════════════════════
# RESOLVER VIEW
# ═══════════════════════════════════════════════════════════════════
class ResolverView(arcade.View):
    def __init__(self):
        super().__init__()
        self.selected = 0
        self.scroll_offset = 0
        self.solution: Optional[list[str]] = None
        self.solving = False
        self.error_msg = ""
        self.background_color = C_BG
        self.replay_engine: Optional[HexobanEngine] = None
        self.replay_moves: list[str] = []
        self.replay_idx = 0
        self.replay_timer = 0.0
        self.replay_speed = 0.35
        # Progress tracking
        self.solve_states = 0
        self.solve_max = 0
        self.solve_elapsed = 0.0
        self.solve_status = ""
        # Combine builtin + saved custom levels
        self.all_levels = list(BUILTIN_LEVELS)
        saved = list_saved_levels()
        for fp in saved:
            data = load_level_file(str(fp))
            if data and "data" in data:
                if not data["name"].startswith("\u2709"):
                    data["name"] = f"\u2709 {data['name']}"
                self.all_levels.append(data)
        log(f"Resolver: {len(self.all_levels)} levels ({len(BUILTIN_LEVELS)} builtin + {len(self.all_levels)-len(BUILTIN_LEVELS)} custom)")

    def on_show_view(self):
        self.background_color = C_BG

    def _visible_count(self):
        return max(1, (self.window.height - HUD_H - HINT_H - 120) // 44)

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        if self.replay_engine:
            self._draw_replay(w, h)
            return
        _draw_hud_bar(w, h, "Resolver", f"{self.selected+1}/{len(self.all_levels)}")
        _draw_hint_bar(w, "Enter=Solve/Replay \u2022 Esc=Back/Cancel")
        vis = self._visible_count()
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + vis:
            self.scroll_offset = self.selected - vis + 1
        start_y = h - HUD_H - 30
        for vi in range(vis):
            idx = self.scroll_offset + vi
            if idx >= len(self.all_levels):
                break
            _draw_list_item(w, start_y - vi * 44, self.all_levels[idx]["name"], idx == self.selected)
        # Check if cached solution exists for selected level
        lv = self.all_levels[self.selected] if self.selected < len(self.all_levels) else None
        cached_info = ""
        if lv and not self.solving and not self.solution and not self.error_msg:
            best = get_best_moves(lv["name"], lv["data"])
            if best is not None:
                cached_info = f"\u2705 Cached: {best} moves \u2014 Enter=Replay"

        if self.solving:
            arcade.Text(self.solve_status or "Solving\u2026",
                        w / 2, HINT_H + 40, C_WARN, 16, anchor_x="center").draw()
            # Progress bar
            if self.solve_max > 0:
                pct = self.solve_states / self.solve_max
                bar_w = 400
                bar_h = 8
                bx = w / 2 - bar_w / 2
                by = HINT_H + 20
                arcade.draw_rect_filled(XYWH(w/2, by, bar_w, bar_h), (40, 40, 55))
                arcade.draw_rect_filled(XYWH(bx + pct*bar_w/2, by, pct*bar_w, bar_h), C_WARN)
        elif self.error_msg:
            arcade.Text(self.error_msg, w / 2, HINT_H + 40, C_ERR, 14,
                        anchor_x="center").draw()
        elif self.solution:
            arcade.Text(f"\u2705 Solution: {len(self.solution)} moves \u2014 Enter=Replay",
                        w / 2, HINT_H + 40, C_SUCCESS, 18, anchor_x="center").draw()
        elif cached_info:
            arcade.Text(cached_info, w / 2, HINT_H + 40, C_SUCCESS, 16,
                        anchor_x="center").draw()

    def _draw_replay(self, w, h):
        eng = self.replay_engine
        # Calculate hex layout for replay
        hex_w = math.sqrt(3)
        hex_h_factor = 1.5
        grid_w_units = eng.cols * hex_w + (hex_w / 2 if eng.rows > 1 else 0)
        grid_h_units = (eng.rows - 1) * hex_h_factor + 2

        playable_h = h - HUD_H - 60
        max_s_w = (w - 40) / grid_w_units if grid_w_units > 0 else 30
        max_s_h = playable_h / grid_h_units if grid_h_units > 0 else 30
        s = min(max_s_w, max_s_h, 36)

        actual_w = grid_w_units * s
        actual_h = grid_h_units * s
        ox = (w - actual_w) / 2 + s * math.sqrt(3) / 2
        oy = (playable_h - actual_h) / 2 + s

        for r in range(eng.rows):
            for c in range(eng.cols):
                hx, hy = hex_center(r, c, s)
                cx = ox + hx
                cy = h - HUD_H - oy - hy
                _draw_tile(cx, cy, s, eng.grid[r][c])
        for br, bc in eng.boxes:
            hx, hy = hex_center(br, bc, s)
            cx = ox + hx
            cy = h - HUD_H - oy - hy
            _draw_box(cx, cy, s, (br, bc) in eng.targets)
        hx, hy = hex_center(eng.player_r, eng.player_c, s)
        px = ox + hx
        py = h - HUD_H - oy - hy
        _draw_player(px, py, s)
        _draw_hud_bar(w, h, f"Replay: {self.replay_idx}/{len(self.replay_moves)}")
        if eng.is_solved():
            arcade.Text("SOLVED!", w / 2, h / 2, C_SUCCESS, 48,
                        anchor_x="center", anchor_y="center", bold=True).draw()

    def on_key_press(self, key, mods):
        if self.replay_engine:
            if key == arcade.key.ESCAPE:
                self.replay_engine = None
                self.solution = None
            return
        if key == arcade.key.ESCAPE:
            if self.solving:
                self.solving = False
                self.error_msg = "Cancelled by user"
                log("Resolver: cancelled by user")
            else:
                self.window.show_view(MenuView())
        elif _is_nav_up(key):
            self.selected = (self.selected - 1) % len(self.all_levels)
            self.solution = None
            self.error_msg = ""
        elif _is_nav_down(key):
            self.selected = (self.selected + 1) % len(self.all_levels)
            self.solution = None
            self.error_msg = ""
        elif key in (arcade.key.RETURN, arcade.key.ENTER):
            if self.solution:
                self._start_replay()
            else:
                # Check cache before solving
                lv = self.all_levels[self.selected]
                cached_moves = get_solution_moves(lv["name"], lv["data"])
                if cached_moves:
                    self.solution = cached_moves
                    log(f"Resolver: loaded cached solution for '{lv['name']}'")
                else:
                    self._solve()
        elif key == self.window.keys.get("key_fullscreen"):
            _toggle_fullscreen(self.window)

    def _on_solve_progress(self, states, max_states, elapsed):
        """Called by solver thread to update HUD progress variables."""
        self.solve_states = states
        self.solve_max = max_states
        self.solve_elapsed = elapsed
        pct = int(100 * states / max_states) if max_states > 0 else 0
        remaining = ((elapsed / states) * (max_states - states)) if states > 0 else 0
        rate = states / elapsed if elapsed > 0 else 0
        self.solve_status = (f"Solving: {states:,}/{max_states:,} ({pct}%) "
                             f"{elapsed:.1f}s ~{remaining:.0f}s left "
                             f"({rate:,.0f} st/s)")
        # Terminal log every 5 seconds
        if not hasattr(self, '_last_term_log') or elapsed - self._last_term_log >= 5.0:
            self._last_term_log = elapsed
            log(f"  Progress: {states:,}/{max_states:,} ({pct}%) "
                f"{elapsed:.1f}s elapsed, ~{remaining:.0f}s remaining, "
                f"{rate:,.0f} states/sec")

    def _solve(self):
        from src.resolver import solve, count_pushes
        lv = self.all_levels[self.selected]
        lv_data = lv["data"]
        lv_name = lv["name"]

        # Check cache first
        cached = load_solution(lv_name, lv_data)
        if cached and cached.get("moves"):
            log(f"Resolver: cache hit for '{lv_name}' ({cached['moves_count']}m)")
            self.solution = cached["moves"]
            self.error_msg = ""
            self.solving = False
            return

        self.solving = True
        self.error_msg = ""
        self.solve_status = "Starting solver..."
        self._last_term_log = 0.0
        log(f"Resolver: solving '{lv_name}'...")

        # Run solver in background thread so HUD can update
        def _worker():
            eng = HexobanEngine()
            eng.load_from_lines(lv_data)
            result = solve(eng, on_progress=self._on_solve_progress)
            # Store result — will be picked up by on_update
            self._solve_result = result
            self._solve_lv_data = lv_data
            self._solve_lv_name = lv_name
            self._solve_done = True

        self._solve_done = False
        self._solve_result = None
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def on_update(self, dt):
        """Check if background solve finished."""
        if self.replay_engine and self.replay_idx < len(self.replay_moves):
            self.replay_timer += dt
            if self.replay_timer >= self.replay_speed:
                self.replay_timer = 0
                self.replay_engine.move(self.replay_moves[self.replay_idx])
                self.replay_idx += 1

        # Check for solve completion from background thread
        if getattr(self, '_solve_done', False):
            self._solve_done = False
            self.solving = False
            result = self._solve_result
            lv_data = self._solve_lv_data
            lv_name = self._solve_lv_name
            if result:
                from src.resolver import count_pushes
                self.solution = result
                pushes = count_pushes(lv_data, result)
                save_solution(lv_name, lv_data, result, pushes, is_best=True)
                log(f"Resolver: solved '{lv_name}' in {len(result)}m {pushes}p — saved")
            else:
                self.error_msg = f"No solution ({self.solve_states:,} states in {self.solve_elapsed:.1f}s)"
                log(f"Resolver: no solution for '{lv_name}'")

    def _start_replay(self):
        lv = self.all_levels[self.selected]
        log(f"Replay: {lv['name']} ({len(self.solution)} moves)")
        self.replay_engine = HexobanEngine()
        self.replay_engine.load_from_lines(lv["data"])
        self.replay_moves = self.solution
        self.replay_idx = 0
        self.replay_timer = 0.0


# ═══════════════════════════════════════════════════════════════════
# REPLAY VIEW — watch proven solutions
# ═══════════════════════════════════════════════════════════════════
class ReplayView(arcade.View):
    def __init__(self):
        super().__init__()
        self.solutions = list_solutions()
        self.selected = 0
        self.scroll_offset = 0
        self.background_color = C_BG
        self.replay_engine: Optional[HexobanEngine] = None
        self.replay_moves: list[str] = []
        self.replay_idx = 0
        self.replay_timer = 0.0
        self.replay_speed = 0.30
        self.replay_name = ""
        log(f"Replay: {len(self.solutions)} saved solutions")

    def on_show_view(self):
        self.background_color = C_BG

    def _visible_count(self):
        return max(1, (self.window.height - HUD_H - HINT_H - 120) // 44)

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        if self.replay_engine:
            self._draw_replay(w, h)
            return
        _draw_hud_bar(w, h, "Replay Solutions", f"{self.selected+1}/{len(self.solutions)}" if self.solutions else "")
        _draw_hint_bar(w, "Enter=Watch \u2022 Esc=Back")
        if not self.solutions:
            arcade.Text("No solutions saved yet.", w / 2, h / 2,
                        C_MENU, 20, anchor_x="center").draw()
            arcade.Text("Solve levels in the Resolver first!",
                        w / 2, h / 2 - 32, C_HINT, 15, anchor_x="center").draw()
            return
        vis = self._visible_count()
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + vis:
            self.scroll_offset = self.selected - vis + 1
        start_y = h - HUD_H - 30
        for vi in range(vis):
            idx = self.scroll_offset + vi
            if idx >= len(self.solutions):
                break
            sol = self.solutions[idx]
            label = f"{sol.get('name','?')} — {sol.get('moves_count','?')}m {sol.get('push_count','?')}p"
            if sol.get("date"):
                label += f"  ({sol['date'][:10]})"
            _draw_list_item(w, start_y - vi * 44, label, idx == self.selected, bar_w=600)

    def _draw_replay(self, w, h):
        eng = self.replay_engine
        hex_w = math.sqrt(3)
        hex_h_factor = 1.5
        grid_w_units = eng.cols * hex_w + (hex_w / 2 if eng.rows > 1 else 0)
        grid_h_units = (eng.rows - 1) * hex_h_factor + 2
        playable_h = h - HUD_H - 60
        max_s_w = (w - 40) / grid_w_units if grid_w_units > 0 else 30
        max_s_h = playable_h / grid_h_units if grid_h_units > 0 else 30
        s = min(max_s_w, max_s_h, 48)
        actual_w = grid_w_units * s
        actual_h = grid_h_units * s
        ox = (w - actual_w) / 2 + s * math.sqrt(3) / 2
        oy = (playable_h - actual_h) / 2 + s
        for r in range(eng.rows):
            for c in range(eng.cols):
                hx, hy = hex_center(r, c, s)
                _draw_tile(ox + hx, h - HUD_H - oy - hy, s, eng.grid[r][c])
        for br, bc in eng.boxes:
            hx, hy = hex_center(br, bc, s)
            _draw_box(ox + hx, h - HUD_H - oy - hy, s, (br, bc) in eng.targets)
        hx, hy = hex_center(eng.player_r, eng.player_c, s)
        _draw_player(ox + hx, h - HUD_H - oy - hy, s)
        _draw_hud_bar(w, h, f"\u25b6 {self.replay_name}", f"{self.replay_idx}/{len(self.replay_moves)}")
        if eng.is_solved():
            arcade.Text("SOLVED!", w / 2, h / 2, C_SUCCESS, 48,
                        anchor_x="center", anchor_y="center", bold=True).draw()

    def on_key_press(self, key, mods):
        if self.replay_engine:
            if key == arcade.key.ESCAPE:
                self.replay_engine = None
            return
        if key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())
        elif _is_nav_up(key) and self.solutions:
            self.selected = (self.selected - 1) % len(self.solutions)
        elif _is_nav_down(key) and self.solutions:
            self.selected = (self.selected + 1) % len(self.solutions)
        elif key in (arcade.key.RETURN, arcade.key.ENTER) and self.solutions:
            self._start_replay()

    def _start_replay(self):
        sol = self.solutions[self.selected]
        moves = sol.get("moves") or sol.get("best_moves")
        if not moves:
            return
        # We need to find the level data — search builtin + saved
        name = sol.get("name", "")
        level_data = None
        for lv in BUILTIN_LEVELS:
            if lv["name"] == name:
                level_data = lv["data"]
                break
        if not level_data:
            for fp in list_saved_levels():
                data = load_level_file(str(fp))
                if data and data.get("name") == name:
                    level_data = data["data"]
                    break
        if not level_data:
            # Try loading by hash match from all saved levels
            log(f"Replay: can't find level data for '{name}'")
            return
        self.replay_engine = HexobanEngine()
        self.replay_engine.load_from_lines(level_data)
        self.replay_moves = moves
        self.replay_idx = 0
        self.replay_timer = 0.0
        self.replay_name = name
        log(f"Replay: playing {name} ({len(moves)} moves)")


# ═══════════════════════════════════════════════════════════════════
# OPTIMIZE VIEW — try to beat existing best score
# ═══════════════════════════════════════════════════════════════════
class OptimizeView(arcade.View):
    def __init__(self):
        super().__init__()
        self.solutions = [s for s in list_solutions() if s.get("moves")]
        self.selected = 0
        self.scroll_offset = 0
        self.background_color = C_BG
        self.optimizing = False
        self.result_msg = ""
        self.solve_status = ""
        log(f"Optimize: {len(self.solutions)} solved levels to optimize")

    def on_show_view(self):
        self.background_color = C_BG

    def _visible_count(self):
        return max(1, (self.window.height - HUD_H - HINT_H - 120) // 44)

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        _draw_hud_bar(w, h, "Optimize Solutions", f"{self.selected+1}/{len(self.solutions)}" if self.solutions else "")
        _draw_hint_bar(w, "Enter=Re-solve \u2022 Esc=Back")
        if not self.solutions:
            arcade.Text("No solutions to optimize.", w / 2, h / 2,
                        C_MENU, 20, anchor_x="center").draw()
            arcade.Text("Solve levels first in the Resolver!",
                        w / 2, h / 2 - 32, C_HINT, 15, anchor_x="center").draw()
            return
        vis = self._visible_count()
        if self.selected < self.scroll_offset:
            self.scroll_offset = self.selected
        elif self.selected >= self.scroll_offset + vis:
            self.scroll_offset = self.selected - vis + 1
        start_y = h - HUD_H - 30
        for vi in range(vis):
            idx = self.scroll_offset + vi
            if idx >= len(self.solutions):
                break
            sol = self.solutions[idx]
            best = sol.get("moves_count", "?")
            pushes = sol.get("push_count", "?")
            label = f"{sol.get('name','?')} — best: {best}m {pushes}p"
            _draw_list_item(w, start_y - vi * 44, label, idx == self.selected, bar_w=600)
        # Status
        if self.optimizing:
            arcade.Text(self.solve_status or "Optimizing\u2026",
                        w / 2, HINT_H + 40, C_WARN, 16, anchor_x="center").draw()
        elif self.result_msg:
            col = C_SUCCESS if "\u2705" in self.result_msg else C_ERR
            arcade.Text(self.result_msg, w / 2, HINT_H + 40, col, 16,
                        anchor_x="center").draw()

    def on_key_press(self, key, mods):
        if key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())
        elif _is_nav_up(key) and self.solutions:
            self.selected = (self.selected - 1) % len(self.solutions)
            self.result_msg = ""
        elif _is_nav_down(key) and self.solutions:
            self.selected = (self.selected + 1) % len(self.solutions)
            self.result_msg = ""
        elif key in (arcade.key.RETURN, arcade.key.ENTER) and self.solutions:
            self._optimize()

    def _on_progress(self, states, max_states, elapsed):
        pct = int(100 * states / max_states) if max_states > 0 else 0
        self.solve_status = f"Re-solving: {states:,}/{max_states:,} ({pct}%) {elapsed:.1f}s"

    def _optimize(self):
        from src.resolver import solve, count_pushes
        sol_data = self.solutions[self.selected]
        old_best = sol_data.get("moves_count", 9999)
        name = sol_data.get("name", "")
        log(f"Optimize: re-solving '{name}' (current best: {old_best}m)")

        # Find level data
        level_data = None
        for lv in BUILTIN_LEVELS:
            if lv["name"] == name:
                level_data = lv["data"]
                break
        if not level_data:
            for fp in list_saved_levels():
                data = load_level_file(str(fp))
                if data and data.get("name") == name:
                    level_data = data["data"]
                    break
        if not level_data:
            self.result_msg = "\u274c Can't find level data"
            return

        self.optimizing = True
        self.solve_status = "Starting optimization..."

        def _worker():
            eng = HexobanEngine()
            eng.load_from_lines(level_data)
            result = solve(eng, on_progress=self._on_progress)
            self._opt_result = result
            self._opt_level_data = level_data
            self._opt_name = name
            self._opt_old_best = old_best
            self._opt_done = True

        self._opt_done = False
        self._opt_result = None
        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def on_update(self, dt):
        if getattr(self, '_opt_done', False):
            self._opt_done = False
            self.optimizing = False
            result = self._opt_result
            name = self._opt_name
            old_best = self._opt_old_best
            level_data = self._opt_level_data
            if result:
                from src.resolver import count_pushes
                pushes = count_pushes(level_data, result)
                if len(result) < old_best:
                    save_solution(name, level_data, result, pushes, is_best=True)
                    self.result_msg = f"\u2705 IMPROVED! {old_best}m \u2192 {len(result)}m ({pushes}p)"
                    log(f"Optimize: improved '{name}' from {old_best}m to {len(result)}m")
                    self.solutions = [s for s in list_solutions() if s.get("moves")]
                elif len(result) == old_best:
                    self.result_msg = f"\u2705 Same: {len(result)}m ({pushes}p) — already optimal"
                    log(f"Optimize: '{name}' already optimal at {old_best}m")
                else:
                    self.result_msg = f"\u2705 Found {len(result)}m but best is {old_best}m"
            else:
                self.result_msg = f"\u274c Could not re-solve (budget exceeded)"



# ═══════════════════════════════════════════════════════════════════
# CREDITS VIEW
# ═══════════════════════════════════════════════════════════════════
class CreditsView(arcade.View):
    def __init__(self):
        super().__init__()
        self.scroll_y = 0.0
        self.background_color = C_BG

    def on_show_view(self):
        self.background_color = C_BG
        self.scroll_y = 0

    def on_draw(self):
        self.clear()
        w, h = self.window.width, self.window.height
        lines = [
            ("H E X O B A N", 40, C_TITLE, True),
            ("", 20, C_HUD, False),
            ("Hexagonal Sokoban", 22, C_HUD, False),
            ("", 16, C_HUD, False),
            ("Built with Python 3.11 & Arcade 3.x", 17, C_MENU, False),
            ("Original Sokoban by Hiroyuki Imabayashi (1981)", 15, C_HINT, False),
            ("Hexagonal grid by David W. Skinner (january 2002)", 15, C_HINT, False),
            ("", 20, C_HUD, False),           
            ("\u2014 Current Hexoban Programmers \u2014", 20, C_TITLE, True),
            ("Claude Opus 4.7", 15, C_HUD, False),
            ("Christophe QUENTIN", 15, C_HUD, False),
            ("source available at  https://github.com/ChristopheQUENTIN-ikigai/Hexoban", 15, C_HUD, False),
            ("", 20, C_HUD, False),
            ("\u2014 Features \u2014", 20, C_TITLE, True),
            ("Hexagonal grid with 6 movement directions", 15, C_HUD, False),
            ("Teleportation portals, cramble tiles steppable one time, locked gate, radioactive tiles and CBRN clothing, switchable laser", 15, C_HUD, False),
            ("20 built-in hex levels (Tutorial \u2192 Hard)", 15, C_HUD, False),
            ("Numpad controls: 7/9/4/6/1/3", 15, C_HUD, False),
            ("QWEASD + arrow key alternatives", 15, C_HUD, False),
            ("Level editor for hex grids", 15, C_HUD, False),
            ("Undo/Redo (500 moves)", 15, C_HUD, False),
            ("Auto-solver (BFS)", 15, C_HUD, False),
            ("Configurable keys (config.json)", 15, C_HUD, False),
            ("", 20, C_HUD, False),
            ("Press Esc to return", 14, C_HINT, False),
        ]
        y = h / 2 + 280 + self.scroll_y
        for text, sz, col, bold in lines:
            if text:
                arcade.Text(text, w / 2, y, col, sz, anchor_x="center", bold=bold).draw()
            y -= sz + 12

    def on_update(self, dt):
        self.scroll_y += dt * 18

    def on_key_press(self, key, mods):
        if key == arcade.key.ESCAPE:
            self.window.show_view(MenuView())


# ═══════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════
def main():
    cfg = load_config("config.json")
    window = HexobanWindow(cfg)
    arcade.run()


if __name__ == "__main__":
    main()
