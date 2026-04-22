"""Smoke tests for the solver with extended tiles.

Run: python tests/test_resolver.py
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.engine import HexobanEngine
from src.resolver import solve, _level_has_extended_tiles


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


def _assert_solution_is_valid(lines, moves):
    """Replay moves on a fresh engine and confirm it ends solved."""
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    for i, d in enumerate(moves):
        assert eng.move(d), f"move {i} ({d}) rejected by engine during replay"
    assert eng.is_solved(), "replayed all moves but puzzle not solved"


def test_classic_sokoban_still_solves():
    """Non-extended levels should use the fast hand-rolled BFS path."""
    lines = ["# # # # #", " # # # #", "# @ $ . #", " # # # #", "# # # # #"]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert not _level_has_extended_tiles(eng)
    sol = solve(eng)
    assert sol == ["RIGHT"]
    _assert_solution_is_valid(lines, sol)


def test_laser_disarmed_by_box_on_slab():
    """Push box onto slab to disarm laser, then walk through."""
    lines = [
        "# # # # # # # # #",
        " #             #",
        "# @ $ a       . #",
        " #     A A A   #",
        "# # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    assert _level_has_extended_tiles(eng)
    sol = solve(eng)
    assert sol is not None, "puzzle should be solvable"
    _assert_solution_is_valid(lines, sol)


def test_key_opens_gate():
    """Pick up a key, walk through matching gate, push box to target."""
    lines = [
        "# # # # # # # #",
        " #           #",
        "# @ e E $ .   #",
        " #           #",
        "# # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    sol = solve(eng)
    assert sol is not None
    assert len(sol) == 3, f"expected 3 moves, got {len(sol)}: {sol}"
    _assert_solution_is_valid(lines, sol)


def test_unsolvable_gate_no_key():
    """Gate blocks the only path and no matching key exists → None."""
    lines = [
        "# # # # # # #",
        " #         #",
        "# @ E $ .   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    sol = solve(eng)
    assert sol is None, "should be unsolvable (locked gate, no key)"


def test_wrong_color_key_does_not_unlock():
    """Key of color 0 and gate of color 1 — puzzle is unsolvable."""
    lines = [
        "# # # # # # # #",
        " #           #",
        "# @ e F $ .   #",
        " #           #",
        "# # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    sol = solve(eng)
    assert sol is None


def test_engine_state_preserved_after_solve():
    """solve() must leave the engine in its initial state."""
    lines = [
        "# # # # # # # #",
        " #           #",
        "# @ e E $ .   #",
        " #           #",
        "# # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    pr0, pc0 = eng.player_r, eng.player_c
    boxes0 = frozenset(eng.boxes)
    keys0 = list(eng.held_keys)
    gates0 = set(eng.opened_gates)
    solve(eng)
    assert (eng.player_r, eng.player_c) == (pr0, pc0), "player moved after solve"
    assert frozenset(eng.boxes) == boxes0, "boxes moved after solve"
    assert eng.held_keys == keys0, "keys changed after solve"
    assert eng.opened_gates == gates0, "gates changed after solve"


def test_builtin_demo_level_solvable():
    """The shipped demo level #26 must be solvable."""
    from src.levels import BUILTIN_LEVELS
    demo = next((lv for lv in BUILTIN_LEVELS if "Laser" in lv["name"]), None)
    assert demo is not None
    eng = HexobanEngine()
    eng.load_from_lines(demo["data"])
    sol = solve(eng)
    assert sol is not None, f"demo level '{demo['name']}' is unsolvable"
    _assert_solution_is_valid(demo["data"], sol)


def test_portal_solving_requires_switch():
    """Puzzle where the goal is only reachable via portal, which needs the
    switch toggled on first."""
    lines = [
        "# # # # # # # # # #",
        " #               #",
        "# @ w     p       #",
        " # # # # # # #   #",
        "#           P $ . #",
        " #               #",
        "# # # # # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    sol = solve(eng)
    assert sol is not None, "portal puzzle should be solvable"
    _assert_solution_is_valid(lines, sol)


def test_colored_box_must_land_on_matching_target():
    """Solver should require color match — level has two boxes, two targets,
    one of each color. Solver must not place them on the wrong targets."""
    lines = [
        "# # # # # # #",
        " #         #",
        "#   1   m   #",
        " #         #",
        "#   2 @ n   #",
        " #         #",
        "# # # # # # #",
    ]
    eng = HexobanEngine()
    eng.load_from_lines(lines)
    sol = solve(eng)
    assert sol is not None, "colored puzzle should be solvable"
    # Replay and verify both boxes are on matching-color targets at the end
    eng2 = HexobanEngine()
    eng2.load_from_lines(lines)
    for d in sol:
        eng2.move(d)
    assert eng2.is_solved(), "solver result must satisfy colored win condition"


def test_builtin_colored_demo_solvable():
    from src.levels import BUILTIN_LEVELS
    demo = next((lv for lv in BUILTIN_LEVELS if "Colored" in lv["name"]), None)
    assert demo is not None
    eng = HexobanEngine()
    eng.load_from_lines(demo["data"])
    sol = solve(eng)
    assert sol is not None, f"colored demo '{demo['name']}' is unsolvable"
    _assert_solution_is_valid(demo["data"], sol)


def main():
    tests = [
        ("classic_sokoban_still_solves", test_classic_sokoban_still_solves),
        ("laser_disarmed_by_box_on_slab", test_laser_disarmed_by_box_on_slab),
        ("key_opens_gate", test_key_opens_gate),
        ("unsolvable_gate_no_key", test_unsolvable_gate_no_key),
        ("wrong_color_key_does_not_unlock", test_wrong_color_key_does_not_unlock),
        ("engine_state_preserved_after_solve", test_engine_state_preserved_after_solve),
        ("builtin_demo_level_solvable", test_builtin_demo_level_solvable),
        ("portal_solving_requires_switch", test_portal_solving_requires_switch),
        ("colored_box_must_land_on_matching_target",
         test_colored_box_must_land_on_matching_target),
        ("builtin_colored_demo_solvable", test_builtin_colored_demo_solvable),
    ]
    print(f"Running {len(tests)} resolver tests...")
    failed = 0
    for name, fn in tests:
        if not _run(name, fn):
            failed += 1
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
