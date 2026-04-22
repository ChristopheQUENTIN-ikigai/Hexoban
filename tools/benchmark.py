#!/usr/bin/env python3
"""Command-line solver benchmark for Hexoban.

Usage:
    python tools/benchmark.py                  # solve all built-in levels
    python tools/benchmark.py 5 10 15         # solve levels 5, 10, 15 (1-indexed)
    python tools/benchmark.py levels/my.json   # solve a level file

Emits a live progress bar while each solve runs (TTY only), a summary
table at the end, and a persistent log at logs/hexoban.log.
"""
import os
import sys
import time
import json
from pathlib import Path

# Run from project root so relative paths resolve
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _project_root)
os.chdir(_project_root)

from src.engine import HexobanEngine
from src.levels import BUILTIN_LEVELS, load_level_file
from src.resolver import solve
from src.solutions import log


def _load_level(arg: str):
    """Resolve an argument to a (name, lines) pair.

    - Integer → that many-th built-in level (1-indexed).
    - Path → load as JSON level file.
    """
    if arg.isdigit():
        idx = int(arg) - 1
        if not (0 <= idx < len(BUILTIN_LEVELS)):
            print(f"  error: built-in index {arg} out of range 1..{len(BUILTIN_LEVELS)}",
                  file=sys.stderr)
            return None
        lv = BUILTIN_LEVELS[idx]
        return (lv["name"], lv["data"])
    p = Path(arg)
    if p.exists():
        data = load_level_file(str(p))
        if data:
            return (data.get("name", p.stem), data["data"])
    print(f"  error: '{arg}' is not an index or a level file", file=sys.stderr)
    return None


def main(argv):
    if not argv:
        targets = [(lv["name"], lv["data"]) for lv in BUILTIN_LEVELS]
    else:
        targets = []
        for a in argv:
            r = _load_level(a)
            if r:
                targets.append(r)
    if not targets:
        print("nothing to solve", file=sys.stderr)
        return 2

    log(f"benchmark: {len(targets)} level(s)")
    results = []
    for name, lines in targets:
        eng = HexobanEngine()
        eng.load_from_lines(lines)
        t0 = time.time()
        sol = solve(eng)
        dt = time.time() - t0
        n_moves = len(sol) if sol else None
        n_pushes = None
        if sol:
            # Count pushes by replay on a clean engine
            eng2 = HexobanEngine()
            eng2.load_from_lines(lines)
            for d in sol:
                eng2.move(d)
            n_pushes = eng2.pushes
        results.append((name, len(eng.boxes), dt, n_moves, n_pushes))

    # Summary table
    print()
    print("Benchmark summary")
    print("-" * 78)
    print(f"  {'Level':<32s} {'Boxes':>6s} {'Time':>10s} {'Moves':>8s} {'Pushes':>8s}")
    print("-" * 78)
    for name, nb, dt, mv, ps in results:
        mv_s = f"{mv:>8d}" if mv is not None else "    FAIL"
        ps_s = f"{ps:>8d}" if ps is not None else "       -"
        print(f"  {name:<32s} {nb:>6d} {dt:>8.2f}s  {mv_s}  {ps_s}")
    print("-" * 78)
    total = sum(r[2] for r in results)
    solved = sum(1 for r in results if r[3] is not None)
    print(f"  {solved}/{len(results)} solved in {total:.1f}s total")
    return 0 if solved == len(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
