"""Unit tests for Hexoban engine mechanics (lasers, slabs, keys, gates).

Run: python -m tests.test_engine   (from project root)
Or:  python tests/test_engine.py
"""
import os
import sys
# Ensure we run from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine import HexobanEngine
from src.levels import (
    parse_level, grid_to_xsb, CHAR_MAP, ID_TO_CHAR,
    slab_id, laser_id, key_id, gate_id,
    is_slab, is_laser, is_key, is_gate,
    is_portal_in, is_portal_out,
    NUM_LASER_GROUPS, NUM_KEY_COLORS,
)


def _run(name, fn):
    try:
        fn()
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:
        print(f"  ERR   {name}: {type(e).__name__}: {e}")
        return False


def test_char_map_coverage():
    """All extended chars map to distinct IDs not overlapping base IDs."""
    for g in range(NUM_LASER_GROUPS):
        assert chr(ord("a") + g) in CHAR_MAP
        assert chr(ord("A") + g) in CHAR_MAP
        assert CHAR_MAP[chr(ord("a") + g)] == slab_id(g)
        assert CHAR_MAP[chr(ord("A") + g)] == laser_id(g)
    for c in range(NUM_KEY_COLORS):
        assert chr(ord("e") + c) in CHAR_MAP
        assert chr(ord("E") + c) in CHAR_MAP
        assert CHAR_MAP[chr(ord("e") + c)] == key_id(c)
        assert CHAR_MAP[chr(ord("E") + c)] == gate_id(c)
    # Extended IDs are distinct among themselves and from base IDs
    extended_ids = {CHAR_MAP[ch] for ch in "abcdABCDefghEFGH"}
    assert len(extended_ids) == 16, "expected 16 distinct extended IDs"
    base_ids = {0, 1, 2, 3, 4, 5, 6, 7}
    assert extended_ids.isdisjoint(base_ids), "extended IDs overlap base IDs"


def test_parse_and_roundtrip_slab_laser():
    """A slab+laser level parses and round-trips through grid_to_xsb."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ a A . #",
        " #       #",
        "# # # # # #",
    ]
    grid, pr, pc = parse_level(lines)
    assert is_slab(grid[2][2]), f"cell (2,2) should be slab, got {grid[2][2]}"
    assert is_laser(grid[2][3]), f"cell (2,3) should be laser, got {grid[2][3]}"
    # Round-trip
    round_lines = grid_to_xsb(grid, pr, pc, set())
    # Re-parse and compare structure
    grid2, pr2, pc2 = parse_level(round_lines)
    assert (pr, pc) == (pr2, pc2)
    assert grid == grid2, f"round-trip failed:\n  {grid}\n  {grid2}"


def test_parse_and_roundtrip_key_gate():
    lines = [
        "# # # # # #",
        " #       #",
        "# @ e E . #",
        " #       #",
        "# # # # # #",
    ]
    grid, pr, pc = parse_level(lines)
    assert is_key(grid[2][2]), f"cell (2,2) should be key, got {grid[2][2]}"
    assert is_gate(grid[2][3]), f"cell (2,3) should be gate, got {grid[2][3]}"
    round_lines = grid_to_xsb(grid, pr, pc, set())
    grid2, _, _ = parse_level(round_lines)
    assert grid == grid2


def test_active_laser_blocks_player():
    """With no slab pressed, laser is ON — player cannot enter."""
    lines = [
        "# # # # #",
        " #     #",
        "# @ A . #",
        " #     #",
        "# # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Attempt to move RIGHT onto laser cell
    moved = eng.move("RIGHT")
    assert not moved, "player should not walk through an active laser"
    assert (eng.player_r, eng.player_c) == (2, 1), \
        f"player should stay at (2,1), is at {(eng.player_r, eng.player_c)}"


def test_slab_disarms_laser():
    """Stepping onto a slab turns off the linked laser (while standing on it)."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ a A . #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Initially laser at (2,3) is ACTIVE — no slab pressed
    assert eng.laser_active(2, 3), "laser should be active initially"
    # Step right onto slab
    assert eng.move("RIGHT"), "player should step onto slab"
    # While standing on slab, laser is OFF
    assert not eng.laser_active(2, 3), "laser should be disarmed by player on slab"
    # Note: the player cannot walk from the slab through the laser because
    # leaving the slab re-arms it. A box or a second slab is required.


def test_laser_rearms_when_slab_vacated():
    """When the player leaves the slab, laser comes back ON."""
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ a A     #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")  # onto slab
    assert not eng.laser_active(2, 3)
    # Walk back left off the slab
    eng.move("LEFT")
    # Laser at (2,3) should be back ON
    assert eng.laser_active(2, 3), "laser should re-arm when slab vacated"


def test_box_on_slab_keeps_laser_off():
    """Pushing a box onto a slab permanently disarms the laser (as long as box stays)."""
    #  @ $ a A .
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ $ a A . #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Push box right → box onto slab, player where box was
    assert eng.move("RIGHT"), "player should push box onto slab"
    # Box now at (2,3), player at (2,2), slab pressed by box
    assert (2, 3) in eng.boxes
    assert not eng.laser_active(2, 4), "laser should be off with box on slab"


def test_key_pickup_and_gate_open():
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ e E .   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Gate is locked initially
    assert eng.held_keys[0] == 0
    # Walk right onto key
    assert eng.move("RIGHT")
    assert eng.held_keys[0] == 1, "key color 0 should be in inventory"
    assert (2, 2) in eng.collected_keys
    # Walk onto gate: should open and consume the key
    assert eng.move("RIGHT")
    assert eng.held_keys[0] == 0, "key consumed on opening gate"
    assert (2, 3) in eng.opened_gates


def test_gate_blocks_without_key():
    lines = [
        "# # # # # #",
        " #       #",
        "# @ E .   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # No key → can't walk through gate
    assert not eng.move("RIGHT"), "gate should block without key"


def test_wrong_color_key_does_not_open_gate():
    """Key of color 0 must not open gate of color 1."""
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ e F .   #",   # key color 0, gate color 1
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert eng.move("RIGHT")  # pick up key color 0
    assert eng.held_keys[0] == 1
    # Gate color 1 still locked
    assert not eng.move("RIGHT"), "gate color 1 should not open with key color 0"


def test_undo_restores_keys_and_gates():
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ e E .   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")  # pick up key
    eng.move("RIGHT")  # open gate, consume key
    assert eng.held_keys[0] == 0
    assert (2, 3) in eng.opened_gates
    # Undo — gate should re-close, key should be back
    eng.undo()
    assert (2, 3) not in eng.opened_gates
    assert eng.held_keys[0] == 1
    eng.undo()
    assert eng.held_keys[0] == 0
    assert (2, 2) not in eng.collected_keys


def test_restart_resets_keys_and_gates():
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ e E .   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")
    eng.move("RIGHT")
    eng.restart()
    assert eng.held_keys == [0, 0, 0, 0]
    assert not eng.opened_gates
    assert not eng.collected_keys
    assert (eng.player_r, eng.player_c) == (2, 1)


def test_pushing_box_onto_active_laser_fails():
    """Cannot push a box into an active laser tile."""
    #  @ $ A .  (no slab, laser is ON)
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ $ A .   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.move("RIGHT"), "box should not be pushable into active laser"


def test_regular_sokoban_still_works():
    """Classic puzzle with no new tiles still solves correctly."""
    lines = [
        "# # # # #",
        " # # # #",
        "# @ $ . #",
        " # # # #",
        "# # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert eng.move("RIGHT")
    assert eng.is_solved()


def test_demo_level_loads():
    """The built-in demo level parses and has the expected tiles."""
    from src.levels import BUILTIN_LEVELS
    demo = None
    for lv in BUILTIN_LEVELS:
        if "Laser" in lv["name"] or "Key" in lv["name"]:
            demo = lv
            break
    assert demo is not None, "no demo level found"
    eng = HexobanEngine()
    eng.load_from_lines(demo["data"])
    # Must have at least one slab, laser, key, gate
    has = {"slab": False, "laser": False, "key": False, "gate": False}
    for r in range(eng.rows):
        for c in range(eng.cols):
            t = eng.grid[r][c]
            if is_slab(t): has["slab"] = True
            if is_laser(t): has["laser"] = True
            if is_key(t): has["key"] = True
            if is_gate(t): has["gate"] = True
    for k, v in has.items():
        assert v, f"demo level missing {k}"


# ─── Portal + switch tests ───

def test_switch_off_portal_acts_as_floor():
    """Switch starts OFF. Stepping on portal-in leaves the player there."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ p P   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.switch_on
    # Step right onto portal-in (p at col 2)
    assert eng.move("RIGHT")
    assert (eng.player_r, eng.player_c) == (2, 2), \
        f"player should be on portal-in, got {(eng.player_r, eng.player_c)}"


def test_switch_toggles_on_step():
    """Stepping onto a switch tile toggles switch_on."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ w w   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.switch_on
    eng.move("RIGHT")  # onto first switch
    assert eng.switch_on, "switch should be ON after first step"
    eng.move("RIGHT")  # onto second switch
    assert not eng.switch_on, "switch should be OFF after second step"


def test_portal_teleports_when_switch_on():
    """Switch ON + step onto portal-in → teleport to portal-out."""
    #   col:  0 1 2 3 4 5 6 7
    #   row2: #   w       p P . #
    # After toggling w, stepping onto p should teleport to P (col 6)
    lines = [
        "# # # # # # # # # #",
        " #               #",
        "# @ w       p P . #",
        " #               #",
        "# # # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Walk right to the switch
    eng.move("RIGHT")
    assert eng.switch_on
    # Walk right repeatedly to the portal-in
    # Player at col 2 (on w), need to reach col 6 (p). Floor between.
    for _ in range(4):
        eng.move("RIGHT")
    # After the step that brought the player onto portal-in, they should
    # have teleported to portal-out (col 7)
    assert (eng.player_r, eng.player_c) == (2, 7), \
        f"expected teleport to (2,7), got {(eng.player_r, eng.player_c)}"


def test_portal_blocked_by_box_on_destination():
    """If portal-out has a box on it, stepping onto portal-in is denied."""
    lines = [
        "# # # # # # # # #",
        " #             #",
        "# @ w     p P   #",
        " #       $     #",
        "# # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Walk to switch first — but wait, box is between. Let me rebuild with
    # explicit geometry: player at (2,1), switch at (2,2), portal-in at
    # (2,5), portal-out at (2,6) with a box on top.
    lines2 = [
        "# # # # # # # # #",
        " #             #",
        "# @ w   $ p P   #",
        " #             #",
        "# # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines2)
    # Check initial positions
    assert eng.player_r == 2 and eng.player_c == 1
    # Need a box on portal-out. Place one by construction: use '*' (box on
    # target)... actually simpler, place the box directly ON portal-out in
    # the grid string. But '$' on 'P' isn't expressible in our format. So
    # I'll push a box there first. Skip this test layout, go different:
    lines3 = [
        "# # # # # # # # #",
        " #             #",
        "# @ w   $   p   #",
        " #           P #",
        "# # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines3)
    # Player at (2,1), switch at (2,2), box at (2,4), portal-in at (2,6),
    # portal-out at (3,6). Plan: toggle switch, push box down so it sits
    # on portal-out, then attempt to step on portal-in (blocked).
    eng.move("RIGHT")     # onto switch
    assert eng.switch_on
    eng.move("RIGHT")     # move toward box
    eng.move("RIGHT")     # push box? Player at (2,3), box at (2,4)
    # Pushing RIGHT: box (2,4) -> (2,5). Now player at (2,4), box at (2,5)
    # Push down-right to land on portal-out (3,6)
    # BR from (2,5) even row = (3,4); that's not portal-out. OK this is
    # getting complicated with hex geometry. Simplify: test the API directly.
    # Just verify the move-guard logic by constructing a state manually.
    eng2 = HexobanEngine()
    eng2.load_from_lines([
        "# # # # # # #",
        " #         #",
        "# @ w p P   #",
        " #         #",
        "# # # # # # #",
    ])
    # Toggle switch on
    eng2.move("RIGHT")
    assert eng2.switch_on
    # Manually place a box on portal-out (2,4) so the teleport is blocked
    eng2.boxes.add((2, 4))
    # Step RIGHT twice to reach portal-in (2,3). First to (2,2)=switch again
    # (would toggle off!) — so let's step a different route. Actually from
    # (2,2) (on switch), step RIGHT to (2,3)=portal-in. But player is ON
    # the switch, stepping to portal-in would teleport, which is blocked.
    # So the move should fail.
    ok = eng2.move("RIGHT")
    assert not ok, "step onto portal-in should fail when destination blocked"


def test_portal_teleport_undoable():
    """Teleport undo restores player to portal-in's cell predecessor."""
    lines = [
        "# # # # # # # # #",
        " #             #",
        "# @ w     p P   #",
        " #             #",
        "# # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")                   # (2,1)->(2,2), toggles switch ON
    eng.move("RIGHT")                   # (2,2)->(2,3)
    eng.move("RIGHT")                   # (2,3)->(2,4)
    eng.move("RIGHT")                   # (2,4)->(2,5), portal-in → teleport to (2,6)
    assert (eng.player_r, eng.player_c) == (2, 6)
    eng.undo()
    # Should be back at (2,4), switch still ON (didn't un-toggle)
    assert (eng.player_r, eng.player_c) == (2, 4)
    assert eng.switch_on
    # Undo more — back to (2,3) then (2,2) then (2,1); switch toggles back OFF at the (2,1) undo
    eng.undo(); eng.undo(); eng.undo()
    assert (eng.player_r, eng.player_c) == (2, 1)
    assert not eng.switch_on


# ─── Colored box / target tests ───

def test_colored_box_parses_and_loads():
    """A colored box '1' on floor: parse, engine picks it up, renders floor."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ 1 m   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Box at (2,2), colored 0 (= '1' which is color 0)
    assert (2, 2) in eng.boxes
    assert eng.box_colors.get((2, 2)) == 0
    # Target at (2,3) is colored 0 (m = color 0)
    assert (2, 3) in eng.targets
    assert eng.target_colors.get((2, 3)) == 0
    # Grid cell under the box is plain FLOOR now
    from src.levels import FLOOR, COLORED_TARGET_BASE
    assert eng.grid[2][2] == FLOOR
    assert eng.grid[2][3] == COLORED_TARGET_BASE  # color-0 target


def test_colored_win_requires_color_match():
    """Color-1 box on color-1 target: win. Color-1 box on color-2 target: no win."""
    # Matching win
    lines_win = [
        "# # # # # #",
        " #       #",
        "# @ 1 m   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines_win)
    assert eng.move("RIGHT")  # push box color 0 onto target color 0
    assert eng.is_solved(), "matching color box on matching target should win"

    # Mismatching colors — box color 0 ('1') pushed onto target color 1 ('n')
    lines_lose = [
        "# # # # # #",
        " #       #",
        "# @ 1 n   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines_lose)
    assert eng.move("RIGHT")
    # Box is at (2,3), target is also at (2,3) in position terms, but colors differ
    assert (2, 3) in eng.boxes
    assert (2, 3) in eng.targets
    assert not eng.is_solved(), "color mismatch must not win"


def test_uncolored_box_does_not_satisfy_colored_target():
    """A common '$' box on a colored 'm' target is NOT a win."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ $ m   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")
    assert (2, 3) in eng.boxes
    assert (2, 3) in eng.targets
    assert not eng.is_solved(), "uncolored box on colored target must not win"


def test_colored_box_does_not_satisfy_uncolored_target():
    """A colored '1' box on a common '.' target is NOT a win."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ 1 .   #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")
    assert not eng.is_solved(), "colored box on uncolored target must not win"


def test_mixed_common_and_colored_boxes_win():
    """A level with both classic '$'/'.' and colored '1'/'m' is won when both match."""
    # Layout (odd-r offset). Player at (2,2), classic '$' at (2,3),
    # classic target '.' at (2,4). Colored box '1' at (3,2), colored
    # target 'm' at (3,3). Walk + push chosen to avoid hex-parity traps.
    lines = [
        "# # # # # # # #",
        " #           #",
        "#   @ $ .     #",
        " #   1 m     #",
        "#             #",
        " # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Step 1: push classic box right onto classic target.
    assert eng.move("RIGHT")
    # Player at (2,3). Now detour around the colored box to push it RIGHT.
    # (2,3) -> BOTTOM_LEFT -> (3,2)? No, that's the colored box -> would push.
    # (2,3) even row: BL = (3,2). That IS the colored box, so RIGHT here
    # would push it further LEFT/RIGHT only via a side approach. Go the
    # long way: (2,3) -> LEFT (2,2) -> LEFT (2,1) -> BL (3,0) -> BR (4,0)?
    # Let me just probe the neighbours to be safe.
    # Simpler: walk back LEFT to (2,2), then BOTTOM_LEFT to (3,1), from
    # which RIGHT pushes the colored box (3,2) -> (3,3).
    assert eng.move("LEFT")          # (2,3) -> (2,2)
    assert eng.move("BOTTOM_LEFT")   # (2,2) even -> (3,1)
    assert eng.move("RIGHT")         # (3,1) odd -> push box (3,2) -> (3,3)
    assert eng.is_solved(), f"mixed puzzle should be won; boxes={eng.boxes}"


def test_push_preserves_box_color():
    """Pushing a colored box preserves its color."""
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ 1       #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert eng.box_colors.get((2, 2)) == 0
    eng.move("RIGHT")  # push box from (2,2) to (2,3)
    assert (2, 3) in eng.boxes
    assert eng.box_colors.get((2, 3)) == 0
    assert (2, 2) not in eng.box_colors


def test_switch_undo_restores_state():
    """Undoing a switch-toggle step reverts switch_on."""
    lines = [
        "# # # # # #",
        " #       #",
        "# @ w     #",
        " #       #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")
    assert eng.switch_on
    eng.undo()
    assert not eng.switch_on


def test_demo_levels_27_28_load():
    """New demo levels load successfully and contain the new tiles."""
    from src.levels import BUILTIN_LEVELS, is_switch as _is_switch
    portal_demo = next((lv for lv in BUILTIN_LEVELS if "Portal" in lv["name"]), None)
    colored_demo = next((lv for lv in BUILTIN_LEVELS if "Colored" in lv["name"]), None)
    assert portal_demo is not None
    assert colored_demo is not None
    # Portal demo has a switch, a portal-in, a portal-out
    eng = HexobanEngine()
    eng.load_from_lines(portal_demo["data"])
    has_pin = has_pout = has_sw = False
    for r in range(eng.rows):
        for c in range(eng.cols):
            t = eng.grid[r][c]
            if is_portal_in(t): has_pin = True
            if is_portal_out(t): has_pout = True
            if _is_switch(t): has_sw = True
    assert has_pin and has_pout and has_sw, \
        f"portal demo missing pieces: in={has_pin} out={has_pout} sw={has_sw}"
    # Colored demo has at least one colored target
    eng2 = HexobanEngine()
    eng2.load_from_lines(colored_demo["data"])
    assert eng2.target_colors, "colored demo should have colored targets"
    assert eng2.box_colors, "colored demo should have colored boxes"


def test_crumble_collapses_after_player_leaves():
    """A crumble tile ('x') becomes void after the player steps off it."""
    from src.levels import CRUMBLE, EMPTY
    lines = [
        "# # # # # #",
        " # # # # #",
        "# @ x .   #",
        " # # # # #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # (2,2) starts as crumble
    assert eng.grid[2][2] == CRUMBLE
    # Step onto the crumble tile — still crumble
    assert eng.move("RIGHT")
    assert eng.grid[2][2] == CRUMBLE, "crumble should not collapse while occupied"
    assert not eng.collapsed_tiles
    # Step off — crumble collapses to void
    assert eng.move("RIGHT")
    assert eng.grid[2][2] == EMPTY, "crumble should collapse once player leaves"
    assert (2, 2) in eng.collapsed_tiles
    # Cannot go back onto the void tile
    assert not eng.move("LEFT"), "void tile should block movement"


def test_crumble_undo_restores_tile():
    """Undoing a crumble collapse restores the tile."""
    from src.levels import CRUMBLE, EMPTY
    lines = [
        "# # # # # #",
        " # # # # #",
        "# @ x .   #",
        " # # # # #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    eng.move("RIGHT")   # onto crumble
    eng.move("RIGHT")   # off — collapses
    assert eng.grid[2][2] == EMPTY
    eng.undo()          # undo the move-off
    assert eng.grid[2][2] == CRUMBLE, "undo should restore collapsed crumble"
    assert (2, 2) not in eng.collapsed_tiles


def test_radioactive_blocks_without_cbrn():
    """Player cannot enter a radioactive tile without CBRN protective clothing."""
    lines = [
        "# # # # # #",
        " # # # # #",
        "# @ R .   #",
        " # # # # #",
        "# # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.has_cbrn
    # Step into radioactive should be denied
    assert not eng.move("RIGHT")
    # Player should be unchanged
    assert (eng.player_r, eng.player_c) == (2, 1)


def test_cbrn_pickup_enables_radioactive_crossing():
    """Picking up CBRN enables traversing radioactive tiles."""
    lines = [
        "# # # # # # #",
        " # # # # # #",
        "# @ S R .   #",
        " # # # # # #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.has_cbrn
    # Step onto CBRN — picks it up
    assert eng.move("RIGHT")
    assert eng.has_cbrn, "CBRN should be picked up on entry"
    assert (2, 2) in eng.collected_cbrn
    # Now step onto radioactive — allowed
    assert eng.move("RIGHT"), "radioactive should be walkable with CBRN"


def test_cbrn_undo_restores_state():
    """Undoing a CBRN pickup removes the suit from the player."""
    lines = [
        "# # # # # # #",
        " # # # # # #",
        "# @ S       #",
        " # # # # # #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert eng.move("RIGHT")
    assert eng.has_cbrn
    eng.undo()
    assert not eng.has_cbrn, "undo should remove CBRN possession"
    assert not eng.collected_cbrn


def test_box_cannot_be_pushed_onto_radioactive():
    """A box cannot be pushed onto a radioactive tile, even with CBRN."""
    lines = [
        "# # # # # # #",
        " # # # # # #",
        "# @ $ R . . #",
        " # # # # # #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    # Push right should fail: box would land on radioactive
    assert not eng.move("RIGHT")


def test_box_cannot_be_pushed_onto_crumble():
    """A box cannot be pushed onto a crumble tile (reserved for player)."""
    lines = [
        "# # # # # # #",
        " # # # # # #",
        "# @ $ x . . #",
        " # # # # # #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not eng.move("RIGHT")


def test_hazard_demo_level_loads():
    """The new 29. Hazard Floor Demo loads and contains the new tiles."""
    from src.levels import (BUILTIN_LEVELS, is_crumble, is_radioactive,
                            is_cbrn_item)
    demo = next((lv for lv in BUILTIN_LEVELS if "Hazard" in lv["name"]), None)
    assert demo is not None, "hazard demo level missing"
    eng = HexobanEngine()
    eng.load_from_lines(demo["data"])
    has_cr = has_rad = has_cbrn = False
    for row in eng.grid:
        for t in row:
            if is_crumble(t): has_cr = True
            if is_radioactive(t): has_rad = True
            if is_cbrn_item(t): has_cbrn = True
    assert has_cr and has_rad and has_cbrn, \
        f"hazard demo missing pieces: crumble={has_cr} radio={has_rad} cbrn={has_cbrn}"


def main():
    tests = [
        ("char_map_coverage", test_char_map_coverage),
        ("parse_roundtrip_slab_laser", test_parse_and_roundtrip_slab_laser),
        ("parse_roundtrip_key_gate", test_parse_and_roundtrip_key_gate),
        ("active_laser_blocks_player", test_active_laser_blocks_player),
        ("slab_disarms_laser", test_slab_disarms_laser),
        ("laser_rearms_when_slab_vacated", test_laser_rearms_when_slab_vacated),
        ("box_on_slab_keeps_laser_off", test_box_on_slab_keeps_laser_off),
        ("key_pickup_and_gate_open", test_key_pickup_and_gate_open),
        ("gate_blocks_without_key", test_gate_blocks_without_key),
        ("wrong_color_key", test_wrong_color_key_does_not_open_gate),
        ("undo_restores_keys_and_gates", test_undo_restores_keys_and_gates),
        ("restart_resets_keys_and_gates", test_restart_resets_keys_and_gates),
        ("pushing_box_into_active_laser_fails", test_pushing_box_onto_active_laser_fails),
        ("regular_sokoban_still_works", test_regular_sokoban_still_works),
        ("demo_level_loads", test_demo_level_loads),
        # Portal / switch
        ("switch_off_portal_acts_as_floor", test_switch_off_portal_acts_as_floor),
        ("switch_toggles_on_step", test_switch_toggles_on_step),
        ("portal_teleports_when_switch_on", test_portal_teleports_when_switch_on),
        ("portal_blocked_by_box_on_destination", test_portal_blocked_by_box_on_destination),
        ("portal_teleport_undoable", test_portal_teleport_undoable),
        ("switch_undo_restores_state", test_switch_undo_restores_state),
        # Colored boxes / targets
        ("colored_box_parses_and_loads", test_colored_box_parses_and_loads),
        ("colored_win_requires_color_match", test_colored_win_requires_color_match),
        ("uncolored_box_does_not_satisfy_colored_target",
         test_uncolored_box_does_not_satisfy_colored_target),
        ("colored_box_does_not_satisfy_uncolored_target",
         test_colored_box_does_not_satisfy_uncolored_target),
        ("mixed_common_and_colored_boxes_win", test_mixed_common_and_colored_boxes_win),
        ("push_preserves_box_color", test_push_preserves_box_color),
        # Demo levels
        ("demo_levels_27_28_load", test_demo_levels_27_28_load),
        # Crumble / Radioactive / CBRN
        ("crumble_collapses_after_player_leaves",
         test_crumble_collapses_after_player_leaves),
        ("crumble_undo_restores_tile", test_crumble_undo_restores_tile),
        ("radioactive_blocks_without_cbrn", test_radioactive_blocks_without_cbrn),
        ("cbrn_pickup_enables_radioactive_crossing",
         test_cbrn_pickup_enables_radioactive_crossing),
        ("cbrn_undo_restores_state", test_cbrn_undo_restores_state),
        ("box_cannot_be_pushed_onto_radioactive",
         test_box_cannot_be_pushed_onto_radioactive),
        ("box_cannot_be_pushed_onto_crumble",
         test_box_cannot_be_pushed_onto_crumble),
        ("hazard_demo_level_loads", test_hazard_demo_level_loads),
    ]
    print(f"Running {len(tests)} tests...")
    failed = 0
    for name, fn in tests:
        if not _run(name, fn):
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
