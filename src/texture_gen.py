"""Auto-generate styled hexagonal textures for Hexoban tiles.

These PNGs are written to assets/textures/ on first launch. Note that
the current in-game renderer draws with Arcade primitives in
src/game.py, not from these PNGs — so changes here only affect:

  * Screenshots and documentation
  * Future sprite-based renderers (not yet wired up)
  * External tools that inspect the assets folder

If you want to change what the GAME actually shows, edit the draw
helpers in src/game.py (_draw_wall_tile, _draw_floor_tile, etc.).
"""
import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

TILE = 64
ASSETS = Path("assets/textures")


def _rgba(r, g, b, a=255):
    return (r, g, b, a)


# Palette — matches the in-game palette in src/game.py so PNG screenshots
# don't look dramatically different from actual gameplay.
WALL_COLOR = _rgba(100, 80, 60)
WALL_SHADOW = _rgba(65, 50, 35)
WALL_HIGHLIGHT = _rgba(135, 108, 82)
WALL_OUTLINE = _rgba(50, 40, 28)

FLOOR_COLOR = _rgba(200, 190, 170)
FLOOR_HIGHLIGHT = _rgba(218, 208, 188)
FLOOR_OUTLINE = _rgba(60, 55, 45)
FLOOR_SPECKLE = _rgba(178, 168, 148)

BOX_COLOR = _rgba(180, 130, 50)
BOX_HIGHLIGHT = _rgba(220, 160, 75)
BOX_OUTLINE = _rgba(140, 100, 30)

BOX_OK = _rgba(100, 180, 80)
BOX_OK_HIGHLIGHT = _rgba(130, 220, 110)
BOX_OK_OUTLINE = _rgba(60, 140, 50)

TARGET_COLOR = _rgba(220, 60, 60)
TARGET_INNER = _rgba(255, 210, 210)
TARGET_OUTLINE = _rgba(180, 40, 40)

PLAYER_COLOR = _rgba(50, 100, 200)
PLAYER_HIGHLIGHT = _rgba(85, 145, 240)
PLAYER_OUTLINE = _rgba(30, 70, 160)
DARK_BG = _rgba(40, 40, 50)


def _hex_points(cx, cy, r):
    """Return pointy-top hex vertices (matches in-game orientation)."""
    pts = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        pts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return pts


def _new_tile(s):
    """Transparent RGBA canvas at supersampled size for cheap AA on save."""
    scale = 2
    return Image.new("RGBA", (s * scale, s * scale), (0, 0, 0, 0)), scale


def _save_downsampled(img, path, s):
    """Downsample by 2× with Lanczos for cheap anti-aliasing."""
    img = img.resize((s, s), Image.LANCZOS)
    img.save(path)


def generate_all(size: int = TILE):
    """Create all styled hex PNGs in assets/textures/."""
    if Image is None:
        print("Pillow not installed — skipping texture generation")
        return
    ASSETS.mkdir(parents=True, exist_ok=True)
    _make_wall(size)
    _make_floor(size)
    _make_box(size)
    _make_box_on_target(size)
    _make_target(size)
    _make_player(size)
    _make_player_on_target(size)
    _make_dark(size)
    print(f"Generated styled hex textures in {ASSETS}/")


def _make_wall(s):
    img, k = _new_tile(s)
    d = ImageDraw.Draw(img)
    cx = cy = s * k / 2
    pts = _hex_points(cx, cy, s * k / 2 - 2)
    d.polygon(pts, fill=WALL_COLOR, outline=WALL_OUTLINE)

    # Lower-half shadow — polygon clipped to bottom ~40% of hex
    sh_pts = [
        (cx + s * k * math.sqrt(3) / 4, cy + s * k * 0.10),
        (cx + s * k * math.sqrt(3) / 4, cy + s * k * 0.30),
        (cx, s * k - 2),
        (cx - s * k * math.sqrt(3) / 4, cy + s * k * 0.30),
        (cx - s * k * math.sqrt(3) / 4, cy + s * k * 0.10),
    ]
    d.polygon(sh_pts, fill=WALL_SHADOW)

    # Upper-left highlight streak
    d.line([(cx - s * k * math.sqrt(3) * 0.48, cy - s * k * 0.25),
            (cx - s * k * 0.05, cy - s * k * 0.90)],
           fill=WALL_HIGHLIGHT, width=2 * k)

    # Two masonry seams
    seam = _rgba(75, 60, 44)
    d.line([(cx - s * k * 0.55, cy - s * k * 0.18),
            (cx + s * k * 0.55, cy - s * k * 0.18)],
           fill=seam, width=1 * k)
    d.line([(cx - s * k * 0.55, cy + s * k * 0.18),
            (cx + s * k * 0.55, cy + s * k * 0.18)],
           fill=seam, width=1 * k)
    # Short vertical tick to imply offset masonry
    d.line([(cx + s * k * 0.05, cy - s * k * 0.18),
            (cx + s * k * 0.05, cy)],
           fill=seam, width=1 * k)

    _save_downsampled(img, ASSETS / "wall.png", s)


def _make_floor(s):
    img, k = _new_tile(s)
    d = ImageDraw.Draw(img)
    cx = cy = s * k / 2
    d.polygon(_hex_points(cx, cy, s * k / 2 - 2), fill=FLOOR_COLOR, outline=FLOOR_OUTLINE)
    d.polygon(_hex_points(cx, cy, s * k * 0.44), fill=FLOOR_HIGHLIGHT)
    d.polygon(_hex_points(cx, cy, s * k * 0.35), fill=FLOOR_COLOR)
    d.ellipse([cx - s * k * 0.32, cy + s * k * 0.13,
               cx - s * k * 0.28, cy + s * k * 0.17], fill=FLOOR_SPECKLE)
    d.ellipse([cx + s * k * 0.23, cy - s * k * 0.22,
               cx + s * k * 0.27, cy - s * k * 0.18], fill=FLOOR_SPECKLE)
    _save_downsampled(img, ASSETS / "floor.png", s)


def _make_box(s, on_target=False):
    img, k = _new_tile(s)
    d = ImageDraw.Draw(img)
    cx = cy = s * k / 2

    # Floor background
    d.polygon(_hex_points(cx, cy, s * k / 2 - 2), fill=FLOOR_COLOR, outline=FLOOR_OUTLINE)

    col = BOX_OK if on_target else BOX_COLOR
    hl = BOX_OK_HIGHLIGHT if on_target else BOX_HIGHLIGHT
    out = BOX_OK_OUTLINE if on_target else BOX_OUTLINE

    # Drop shadow
    shadow_pts = _hex_points(cx + 2 * k, cy + 3 * k, s * k * 0.36)
    d.polygon(shadow_pts, fill=_rgba(20, 20, 30, 180))

    # Main body
    d.polygon(_hex_points(cx, cy, s * k * 0.36), fill=col, outline=out)
    d.polygon(_hex_points(cx, cy, s * k * 0.26), fill=hl)
    d.polygon(_hex_points(cx, cy, s * k * 0.18), fill=col)
    d.polygon(_hex_points(cx, cy, s * k * 0.36), outline=out, width=2 * k)

    # Diagonal cross
    m = s * k * 0.2
    d.line([(cx - m, cy - m * 0.55), (cx + m, cy + m * 0.55)], fill=out, width=k)
    d.line([(cx + m, cy - m * 0.55), (cx - m, cy + m * 0.55)], fill=out, width=k)

    # Rivets at 6 corners
    rivet_r = s * k * 0.03
    for i in range(6):
        angle = math.radians(60 * i - 30)
        rx = cx + s * k * 0.29 * math.cos(angle)
        ry = cy + s * k * 0.29 * math.sin(angle)
        d.ellipse([rx - rivet_r, ry - rivet_r, rx + rivet_r, ry + rivet_r], fill=out)

    path = ASSETS / ("box_on_target.png" if on_target else "box.png")
    _save_downsampled(img, path, s)


def _make_box_on_target(s):
    _make_box(s, on_target=True)


def _make_target(s):
    img, k = _new_tile(s)
    d = ImageDraw.Draw(img)
    cx = cy = s * k / 2
    d.polygon(_hex_points(cx, cy, s * k / 2 - 2), fill=FLOOR_COLOR, outline=FLOOR_OUTLINE)
    d.polygon(_hex_points(cx, cy, s * k * 0.44), fill=FLOOR_HIGHLIGHT)
    d.polygon(_hex_points(cx, cy, s * k * 0.35), fill=FLOOR_COLOR)

    # Bullseye rings
    r_outer = s * k * 0.17
    r_mid = s * k * 0.125
    r_inner = s * k * 0.045
    d.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
              outline=TARGET_OUTLINE, width=k)
    d.ellipse([cx - r_mid, cy - r_mid, cx + r_mid, cy + r_mid],
              fill=TARGET_COLOR, outline=TARGET_OUTLINE, width=2 * k)
    d.ellipse([cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
              fill=TARGET_INNER)
    _save_downsampled(img, ASSETS / "target.png", s)


def _make_player(s, on_target=False):
    img, k = _new_tile(s)
    d = ImageDraw.Draw(img)
    cx = cy = s * k / 2
    d.polygon(_hex_points(cx, cy, s * k / 2 - 2), fill=FLOOR_COLOR, outline=FLOOR_OUTLINE)

    if on_target:
        r_halo = s * k * 0.21
        d.ellipse([cx - r_halo, cy - r_halo, cx + r_halo, cy + r_halo],
                  outline=TARGET_COLOR, width=2 * k)

    r_body = s * k * 0.19
    # Drop shadow
    d.ellipse([cx - r_body + 1 * k, cy - r_body + 2 * k,
               cx + r_body + 1 * k, cy + r_body + 2 * k],
              fill=_rgba(20, 20, 30, 180))

    # Body + highlight crescent
    d.ellipse([cx - r_body, cy - r_body, cx + r_body, cy + r_body],
              fill=PLAYER_COLOR, outline=PLAYER_OUTLINE, width=2 * k)
    r_hl = r_body * 0.55
    d.ellipse([cx - r_body * 0.3 - r_hl, cy - r_body * 0.3 - r_hl,
               cx - r_body * 0.3 + r_hl, cy - r_body * 0.3 + r_hl],
              fill=PLAYER_HIGHLIGHT)
    d.ellipse([cx - r_body * 0.88, cy - r_body * 0.88,
               cx + r_body * 0.88, cy + r_body * 0.88], fill=PLAYER_COLOR)
    d.ellipse([cx - r_body, cy - r_body, cx + r_body, cy + r_body],
              outline=PLAYER_OUTLINE, width=2 * k)

    # Eyes
    eye_r = s * k * 0.05
    pup_r = s * k * 0.022
    for ex in (cx - s * k * 0.06, cx + s * k * 0.06):
        d.ellipse([ex - eye_r, cy + s * k * 0.03 - eye_r,
                   ex + eye_r, cy + s * k * 0.03 + eye_r],
                  fill=_rgba(255, 255, 255))
        d.ellipse([ex - pup_r, cy + s * k * 0.03 - pup_r,
                   ex + pup_r, cy + s * k * 0.03 + pup_r],
                  fill=_rgba(20, 20, 40))

    # Smile arc
    smile_box = [cx - s * k * 0.06, cy - s * k * 0.06,
                 cx + s * k * 0.06, cy + s * k * 0.02]
    d.arc(smile_box, 200, 340, fill=_rgba(20, 20, 40), width=k)

    path = ASSETS / ("player_on_target.png" if on_target else "player.png")
    _save_downsampled(img, path, s)


def _make_player_on_target(s):
    _make_player(s, on_target=True)


def _make_dark(s):
    img = Image.new("RGBA", (s, s), DARK_BG)
    img.save(ASSETS / "dark.png")


if __name__ == "__main__":
    generate_all()
