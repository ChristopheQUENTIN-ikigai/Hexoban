# Hexoban — Hexagonal Sokoban

A hexagonal variant of the classic Sokoban puzzle game, built with **Python 3.11** and **Arcade 3.x**.

In Hexoban the board is made of hexagons instead of squares, giving **6 directions** to move instead of four. 

## Quick Start

```bash
pip install arcade Pillow
python main.py
```

Launches in **fullscreen** by default. Press **F** to toggle windowed mode.
Placeholder textures are auto-generated on first launch.

## Features

- **Hexagonal grid** with pointy-top hexagons and 6 movement directions
- **29 built-in hex levels** — 5 difficulty tiers + four mechanics demos
- **Pressure-plate lasers** — step or push a box onto a slab to disarm its linked laser beams
- **Colored keys and gates** — collect a key to pass through the same-colored gate
- **Portals + switch** — step on the switch to enable teleport from blue portal to orange portal
- **Colored boxes and targets** — each colored box must be pushed to its own matching-color target; common boxes still go on any common target
- **Crumble floors** — single-use tiles that collapse into void once the player steps off
- **Radioactive floors + CBRN suit** — deadly tiles that can only be crossed once the player has picked up the CBRN protective clothing
- **Multiple control schemes**: Numpad (7/9/4/6/1/3), QWEASD, and arrow keys
- **Clock timer** in HUD — track your solve time
- **Level editor** — mouse painting on hex grid, 24 tools including all extended tiles, default 21×13 grid, resize up to 30×30, undo, save & test
- **Auto-solver** — engine-driven BFS, correct for every mechanic (lasers, slabs, keys, gates, portals, switches, colored boxes, crumble, radioactive, CBRN), animated replay
- **Undo/Redo** — up to 500 moves deep; reverses teleports, switch toggles, key pickups, gate openings, crumble collapses, and CBRN pickups
- **Fully configurable** — keys, display, game settings in `config.json`
- **Fullscreen by default** — press F to toggle; auto-detects screen size
- **Responsive layout** — adapts to any window size

## New mechanics

### Lasers and slabs

Some levels contain **deadly laser beams** that block movement in both directions — stepping into an active laser is not allowed. Each laser belongs to a **group** (1–4). Each group may have one or more **slabs** (pressure plates) somewhere on the map.

When **at least one slab** in a given group is occupied by the player **or** a box, every laser in that group switches **off** and can be walked through freely. The moment every slab in the group becomes empty, the lasers switch back on.

Tactically this means:
- You can pass through a laser while standing on its slab, but you cannot leave the slab without the laser re-arming behind you.
- Pushing a **box** onto a slab is usually what you want — it holds the slab down permanently while you move through the laser.

### Colored keys and gates

Some levels contain **colored gates** (1–4) that block the player until they have collected a matching **key**. Walking over a key picks it up and stores it in the player's inventory — shown as small colored icons in the HUD. Walking into a matching-color gate **consumes one key** and opens the gate permanently (both gate-opening and key-pickup are undoable).

Boxes cannot push onto key tiles (the key is fragile), and cannot pass through closed gates.

### Portals and the electrical switch

Levels may contain one **blue portal** (entry), one **orange portal** (destination), and one **electrical switch**. The portal is **unidirectional**: stepping onto the blue portal teleports the player to the orange portal, but stepping onto orange does nothing — it's only a destination.

Portals require power. Stepping onto the switch **toggles** it between ON and OFF. When the switch is **OFF**, the blue portal acts as ordinary floor and the player can stand on it harmlessly. When the switch is **ON**, stepping onto blue portal-in mandatorily teleports the player to orange portal-out. If the orange portal is blocked by a box, the move into blue portal-in is rejected.

Boxes do not travel through portals — only the player does. A box pushed onto a blue portal simply rests there.

### Colored boxes and colored targets

A level can mix **common boxes** (classic brown/green, any-target) with **colored boxes** (red, cyan, lime, purple — up to 4 colors). Colored boxes must be pushed onto a **colored target** of the same color to count toward the win condition. Common boxes match common targets.

The level is solved when every target has a compatible box on it and every box sits on a compatible target — so a colored box on a common target does not count, and neither does a common box on a colored target.

### Crumble floors

A **crumble tile** looks like a floor tile with jagged cracks across it. The player can step onto it, but the moment the player steps **off**, the tile **collapses into void** and is gone for the rest of the level. This makes crumble floors **single-use** — a level designer can force a one-way corridor or punish a player who revisits their path.

Boxes cannot be pushed onto crumble tiles: the collapse mechanic is reserved for the player. Undoing the move that triggered the collapse restores the crumble tile, so players can backtrack freely while exploring.

### Radioactive floors and the CBRN suit

A **radioactive tile** shows the international trefoil symbol on a bright yellow disc. Stepping onto one is **deadly** and the move is denied — unless the player is wearing **CBRN protective clothing** (a pickup item shown as a hazmat-green humanoid silhouette with a dark visor).

Walking onto the CBRN item **picks it up automatically** and permanently changes the player's appearance: the standard blue character is replaced by a hazmat-suited figure with a dark visor in place of eyes, making it instantly obvious that radioactive traversal is now safe. Pickup is undoable — undo removes the suit from the player.

Boxes cannot be pushed onto radioactive tiles or CBRN items: pushing a box onto a radioactive tile would leave a hazardous obstacle, and pushing onto the CBRN item would consume it without pickup.

## Hex Grid Coordinate System

Hexoban uses **offset coordinates (odd-r)** with pointy-top hexagons:
- Even rows are aligned left
- Odd rows are shifted right by half a hex width
- 6 neighbors per cell (vs 4 in standard Sokoban)

```
    / \   / \   / \
   | 0,0 | 0,1 | 0,2 |
    \ / \ / \ / \ /
     | 1,0 | 1,1 | 1,2 |    ← odd row shifted right
    / \ / \ / \ / \
   | 2,0 | 2,1 | 2,2 |
    \ / \ / \ / \ /
```

## Controls

### Game Controls (6 Hex Directions)

| Key | Direction |
|-----|-----------|
| Numpad 7 / Q | Top-Left ↖ |
| Numpad 9 / E | Top-Right ↗ |
| Numpad 4 / A | Left ← |
| Numpad 6 / D | Right → |
| Numpad 1 / X | Bottom-Left ↙ |
| Numpad 3 / C | Bottom-Right ↘ |

Arrow keys also work as approximate mappings (Left/Right = hex Left/Right, Up = Top-Right, Down = Bottom-Left).

### Other Controls

| Key | Action |
|-----|--------|
| U | Undo |
| Y | Redo |
| R | Restart level |
| F | Toggle fullscreen |
| H | Help overlay |
| M | Back to menu |
| Esc | Quit / Back |

## Editor Controls

| Key / Mouse | Action |
|-------------|--------|
| Click / drag | Paint hex tiles |
| 1–4 | Void / Wall / Floor / Target |
| 5 or P | Player placement |
| 6 or B | Box placement |
| **7** | **Slab** (pressure plate) |
| **8** | **Laser** (deadly beam) |
| **9** | **Key** |
| **0** | **Gate** |
| Click toolbar | Portal-In, Portal-Out, Switch, Colored Target, Colored Box (new in v3) |
| **, / .** | **Cycle slab/laser group, key/gate color, or colored box/target color** |
| Tab | Cycle tools |
| ] / [ | Add / remove rows |
| = / - | Add / remove columns |
| Z | Undo |
| S | Save level |
| T | Test play |
| V | Solve (check solvability) |
| G | Analyze (difficulty) |
| F | Auto-walls |
| C | Clear grid |

The currently-selected group (for slabs/lasers), color (for keys/gates), or box color (for colored targets/boxes) is shown inline on each of those tool buttons, and can be changed with `,` / `.` at any time. The portal, portal-out, and switch tools are single-instance — there is at most one of each per level.

## Configuration

Settings are stored in `config.json` (JSON format):

```json
{
    "display": {
        "autodetect": true,
        "default_width": 1024,
        "default_height": 768,
        "tile_size": 64,
        "fullscreen": true
    },
    "keys": {
        "move_top_left": "KP_7",
        "move_top_right": "KP_9",
        "move_left": "KP_4",
        "move_right": "KP_6",
        "move_bottom_left": "KP_1",
        "move_bottom_right": "KP_3",
        "undo": "z",
        "redo": "y",
        "restart": "r",
        "fullscreen_toggle": "f",
        "quit": "ESCAPE",
        "help": "h",
        "menu": "m"
    },
    "game": {
        "max_undo": 500,
        "animation_speed": 8.0
    }
}
```

## Level Format

Hexoban levels use a spaced XSB-like format where each character is separated by spaces. Odd rows have a leading space to represent the hex offset:

```
# # # # # # # # # # #
 #                 #
# @   a   A A A     #
 #                 #
#       $ e E . #   #
 #                 #
# # # # # # # # # # #
```

### Character reference

| Char | Meaning |
|------|---------|
| `#` | wall |
| `@` | player |
| `+` | player on target |
| `$` | box (classic, any-target) |
| `*` | box on target |
| `.` | target (classic, any-box) |
| ` ` (space) | floor |
| `_` | empty / void (no hex) |
| `a` `b` `c` `d` | slab (pressure plate) for laser group 1–4 |
| `A` `B` `C` `D` | laser beam of group 1–4 |
| `e` `f` `g` `h` | key of color 1–4 |
| `E` `F` `G` `H` | gate of color 1–4 |
| `p` | portal-in (blue entry) |
| `P` | portal-out (orange destination) |
| `w` | electrical switch (latches on/off) |
| `m` `n` `o` `v` | colored target of color 1–4 |
| `1` `2` `3` `4` | colored box of color 1–4 (on floor) |
| `M` `N` `O` `V` | colored box of color 1–4 sitting on matching colored target |
| `x` | crumble floor (single-use; collapses to void after player leaves) |
| `R` | radioactive floor (deadly without CBRN suit) |
| `S` | CBRN protective clothing item (picked up on entry) |

Lowercase = slab, key, portal-in, switch, colored target, or crumble floor (ground-level, walkable). Uppercase = laser, gate, portal-out, colored-box-on-target, radioactive, or CBRN item. Slab `a` links to laser `A`; key `e` unlocks gate `E`; colored box `1` belongs on colored target `m`; `S` must be collected before crossing `R`; `x` is single-use.

## Testing

```bash
python tests/test_engine.py    # 36 tests — movement, lasers, keys/gates, portals, switch, colored boxes, crumble, radioactive, CBRN, undo
python tests/test_resolver.py  # 10 tests — classic + extended solver correctness, state preservation
```

## Project Structure

```
hexoban/
├── main.py                 # Entry point
├── config.json             # Key bindings & display settings (JSON)
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── REVIEW.md               # Maintainability & resolver-efficiency proposals
├── assets/textures/        # Auto-generated placeholder sprites
├── assets/solutions/       # Cached best solutions per level
├── levels/                 # User-saved custom levels (.json)
├── tests/                  # Engine & resolver test suites
└── src/
    ├── __init__.py
    ├── config_loader.py    # JSON config parser, screen auto-detect
    ├── engine.py           # Hex game logic (6 dirs, laser/slab/key/gate/portal/crumble/radio)
    ├── game.py             # Arcade 3.x Views (hex rendering, all screens)
    ├── levels.py           # Hex level data, parser, tile IDs, save/load
    ├── resolver.py         # BFS/A*/macro solver; engine-driven BFS for extended levels
    ├── solutions.py        # Solution cache and difficulty classifier
    └── texture_gen.py      # Pillow placeholder sprite generator
```

## History

From 2002, for several following years the Sokoban community explored the Hexoban variant based on an idea from David W. Skinner. Several well-known Sokoban authors created hexoban puzzles, including David Holland, Erim Sever, François Marques, Gerald Holler, Aymeric Du Peloux, J. Kenneth Riviere, and Lee Haywood. There was even a short-lived monthly competition at François Marques' website. Programmers including Victor Kindermans, Paul Voyer, Fabricio C. Zuardi, and George Petrov created programs and utilities for Hexoban.

## License
M.I.T. License, Educational project. 
Original Sokoban concept by Hiroyuki Imabayashi (1981). Hexagonal grid by David W. Skinner in january 2002 . Laser/slab and key/gate mechanics, Portal/switch and colored-box mechanics , Crumble floors and radioactive/CBRN mechanics added 2026.
