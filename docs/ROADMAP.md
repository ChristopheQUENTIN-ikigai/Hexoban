# Hexoban — Development Roadmap

Forward-looking document that captures **where the project is today** and
**what to consider next**. Focused on the solver, since that's where
most of the interesting engineering decisions live, but also covers
engine mechanics and editor UX.

This is meant to be read start-to-finish once and then kept as a
reference. For narrower code-review style notes, see `REVIEW.md`.

---

## 1. What the solver does today

The solver in `src/resolver.py` is a **cascade of four strategies**
tried in order. Each is a complete solver on its own; the cascade exists
so that trivial levels don't pay the overhead of sophisticated search,
and hard levels still get solved.

### 1.1 Dispatch

`solve(engine)` examines the level and picks a path:

```
solve(engine)
  │
  ├─► If level has extended tiles (slabs / lasers / keys / gates /
  │   portals / switch / colored boxes or targets):
  │     └─► _solve_bfs_extended    (engine-driven BFS)
  │
  └─► Otherwise (classic Sokoban):
        ├─► 1 box OR ≤30 floor cells     → _solve_bfs
        ├─► ≤3 boxes OR ≤80 floor cells  → _solve_astar  (3M budget)
        ├─► ≥2 boxes                     → _solve_macro  (1M/box budget)
        └─► fallback                     → _solve_astar  (5M budget)
```

The dispatch is intentionally conservative: a level with ANY extended
tile bypasses the classic solvers, because re-implementing extended
semantics in every solver would duplicate logic and risk drift. The
engine-driven BFS handles all mechanics by delegating to `engine.move()`
and `engine.is_solved()`.

### 1.2 `_solve_bfs` — breadth-first search

Standard BFS over the state space `(player_r, player_c, frozenset(boxes))`.
Returns the **optimal move-count** solution if one exists within budget.

- **Complete** and **optimal** in move count.
- **Expensive on large puzzles**: state space is roughly
  `(floor cells)! / ((floor - N)! × N!)` for N boxes, exponential in N.
- Used only for 1-box levels or very small floors (≤30 cells) where
  exhaustive search is cheap.

### 1.3 `_solve_astar` — A* with push-distance heuristic

A* over the same state space, using the sum of per-box push-distance
estimates as the heuristic `h`. Push-distance is precomputed once at
solve start by reverse-BFS from each target, modeling the minimum pushes
required from every cell to each target.

- **Complete** and **optimal** under an admissible heuristic. Push-
  distance is admissible *if computed ignoring other boxes*, which it is.
- **Much faster than BFS** on puzzles with 2-3 boxes: the heuristic
  prunes the vast majority of non-productive expansions.
- Falls back to hex-distance heuristic on large floors (>300 cells)
  where the reverse-BFS precompute would itself be expensive.

### 1.4 `_solve_macro` — per-box decomposition

Rather than searching the combined state space, the macro-solver
**assigns each box to a target** (greedy by push-distance), then **solves
one box at a time** with A*. Boxes not currently being moved are treated
as immovable obstacles. Once a box is on its target it becomes a wall
for subsequent passes.

- **Not optimal** — the greedy assignment and per-box ordering can miss
  solutions that require interleaving box motions.
- **Tractable on large open maps** where full A* would explode.
- Tries two orderings (original and reversed) before giving up.
- This mimics how humans solve large Sokoban puzzles: decompose,
  sequence, commit.

### 1.5 `_solve_bfs_extended` — engine-driven BFS

The solver that handles all the extended mechanics. State key is:

```
(player_r, player_c,
 frozenset(boxes),
 tuple(held_keys),
 frozenset(opened_gates),
 frozenset(collected_keys),
 box_colors_tuple,
 switch_on)
```

Every candidate move is attempted by calling `engine.move(direction)`
on a shared engine instance. State is saved and restored via
`engine._snapshot()` / `engine._restore()` between attempts, so the
engine never holds stale state between branches.

- **Correctness guarantee**: every mechanic is handled by the engine,
  so adding a new tile type to the engine requires zero changes to the
  solver's legality logic.
- **Overhead per expansion**: each move costs a snapshot + engine.move
  + snapshot + restore, which is several times slower than a hand-rolled
  inline move loop. Typically 5–10× slower per state than the classic
  solvers would be on the same state space.
- **Correctness has been worth it**: two full cycles of new mechanics
  (v2 added 4, v3 added 3) needed ≤5 lines of solver changes each.

### 1.6 Deadlock detection

`_is_hex_deadlock(engine, r, c)` flags a box in a corner where three
consecutive hex directions are blocked by walls or void. Used by the
classic solvers to prune states where a box is obviously unsolvable.

- **Conservative on purpose**: only unconditionally-blocking tiles
  (WALL, EMPTY) count as blockers. Lasers and closed gates are
  conditional and are NOT counted — treating them as walls would
  incorrectly prune valid states.
- **Not used by the extended BFS** — that solver relies on full state
  exploration and lets dead-end states exhaust on their own. On hard
  colored-box puzzles this causes visible slowdown; adding a colored-
  aware corner check to the extended path is in the roadmap below.

### 1.7 Benchmark reference points

Measured on the committed tests with CPython 3.11:

| Level                         | Boxes | Solver          | Moves | States    | Time    |
|-------------------------------|------:|-----------------|------:|----------:|--------:|
| Classic #1 "First Push"       |     1 | BFS             |     1 |         1 |  <0.01s |
| Demo #27 "Portal Switch"      |     1 | engine-driven   |     7 |        40 |  <0.01s |
| Demo #26 "Laser & Key"        |     1 | engine-driven   |    13 |     1,484 |   0.09s |
| Classic #19 "Hex Fortress"    |     4 | A*              |    22 |     ~12 K |   0.03s |
| Classic #20 "Open Four"       |     4 | A*              |    32 |     ~95 K |   0.14s |
| Classic #24 "Hex Extreme"     |     4 | A*/macro        |    22 |    ~1.2 M |   2.61s |
| Demo #28 "Colored Boxes"      |     3 | engine-driven   |    12 |    31,275 |   2.73s |

The colored-box demo takes longer than the classic hard level despite
having one fewer box — that's the per-state overhead of the engine-
driven BFS plus the dedup cost of distinguishing box identities.

---

## 2. Engine mechanics in use today

For completeness — the solver operates against an engine that handles:

1. **Classic Sokoban**: push/move/undo/redo/restart.
2. **Slabs + lasers**: slab pressure disarms linked laser groups;
   laser re-arms when the slab is vacated. 4 independent groups.
3. **Colored keys + gates**: key pickup, gate consumption, 4 colors.
4. **Portal (single pair) + switch**: mandatory teleport from blue to
   orange when the switch is on; blocked by box on destination.
5. **Colored boxes + colored targets**: per-color match required for
   win; mixes freely with classic uncolored boxes/targets.

All mechanics share one `GameState` dataclass and one `move()`
implementation. Undo/redo/restart reverse every state transition
including switch toggles, teleports, and key consumption.

The single-source-of-truth engine is the most important architectural
property of this project. Most roadmap items below either build on it
or explicitly trade it away; weigh that cost honestly.

---

## 3. Optimization approaches — pros, cons, when to reach for each

Ranked by return-per-effort for this specific codebase. Speedups are
rough estimates on hard levels (not trivial ones — those are already
fast enough that nothing helps).

### 3.1 Algorithmic wins in pure Python  ⭐ Do this first

| Item | Expected speedup | Effort | Cost |
|------|-----------------:|-------:|------|
| Parent-pointer path reconstruction | 2–5× | half-day | none |
| Precomputed neighbor / walkability tables | 1.5–3× | half-day | none |
| Per-cell deadlock cache | 1.2–2× | hour | none |
| Slab-position index at load | 1.3–2× on laser levels | hour | touches engine too |
| Bitmask-packed state (small grids) | 2–4× | day | small grids only |

**Pros:** No new dependencies, no build-system changes, works on every
Python install, keeps the engine as single source of truth, is
composable with every accelerator below.

**Cons:** Caps out at perhaps 5–10× combined. Won't turn a 5-minute
solve into a 5-second solve.

**When:** Always. Everything else multiplies against this baseline.

**Concrete first patch:** parent pointers. The current BFS carries
`path + [d]` per queue entry (O(depth) allocation per expansion).
Replacing it with a `parent: dict[state_key, (prev_key, dir)]` and
walking backward at the end is maybe 30 lines of code and typically
the single biggest win.

### 3.2 PyPy as a solver subprocess  ⭐ Best single "bang-for-buck"

| Aspect | Assessment |
|--------|------------|
| Expected speedup | 5–15× on top of §3.1 |
| Effort | ~80 lines of subprocess plumbing |
| Dependency cost | PyPy is optional; absent → fall back to in-process CPython |

**How:** PyPy is a separate Python runtime with a tracing JIT. On
hash-heavy BFS code it delivers 5–15× over CPython with zero source
changes. Arcade doesn't support PyPy cleanly so you can't run the
whole app under it — but you can spawn a PyPy subprocess for the
solver alone.

```
 GUI (CPython+Arcade)  ── stdin JSON level ──►  PyPy solver subprocess
        │                                             │
        └────── reads JSON moves list from stdout ◄──┘
```

**Pros:** Zero code changes to engine or solver. Keeps single source
of truth. Opt-in install. IPC overhead amortizes to negligible for
any solve taking >100 ms.

**Cons:** Subprocess startup (~20–50 ms) + JSON IPC — dispatch only if
the puzzle is worth it. Needs PyPy installed to see the win; without
it, no speedup but also no regression.

**When:** After §3.1 if editor `Solve`/`Analyze` still feels slow on
the levels users care about.

### 3.3 Threading the editor's `Solve` / `Analyze`  ⭐ Fixes UI freeze

| Aspect | Assessment |
|--------|------------|
| Expected speedup | Zero — this is a UX fix, not a perf fix |
| Effort | ~30 lines (copy pattern from ResolverView) |
| Dependency cost | none |

**What it fixes:** The editor calls `solve()` synchronously from
`on_key_press`. Even a 500 ms solve freezes the window (no repaint, no
input). On a hard colored level the freeze lasts seconds and looks like
a crash.

**How:** Mirror the worker-thread pattern already in `ResolverView`:
spawn a thread, poll `job.done` from `on_update`, show a "solving..."
overlay with a progress bar (data already available via
`on_progress`), allow cancel.

**Pros:** Changes the entire perceived responsiveness of the editor
without touching solver algorithms. The user's original "CPU freezes"
complaint was partly this and partly algorithmic — this half of the
fix is nearly free.

**When:** Same day as §3.1, independent of it.

### 3.4 Bitmask-packed state in pure Python

If the level's reachable floor has ≤63 cells, the set of box positions
fits in a single 64-bit int. State key becomes `(player_idx: int,
boxes: int, switch: bool, held_keys: tuple, ...)` — all integers.

**Pros:** 2–4× on small levels from CPython alone. Python's int hash
is blazingly fast. Memory per visited state drops by an order of
magnitude. Composes with everything.

**Cons:** Only applies to small grids. Requires a precomputed cell-
index table and a "decode box mask → positions" routine for rendering
solutions back into move lists.

**When:** If your level sizes stay bounded. Hexoban's built-in levels
all fit. Custom levels may not.

### 3.5 Numba (considered and rejected for this codebase)

Numba JITs numeric Python. The sweet spot is NumPy-array loops.

**Why it doesn't fit here:** Our state is
`(int, int, frozenset[tuple[int,int]], tuple[int,...], frozenset, bool)`.
`nopython` mode rejects frozensets and heterogeneous tuples of tuples.
`typed.Dict` / `typed.Set` exist but are modest wins for compound
keys — typically 1.5–2× over CPython.

The only way Numba pays off is if state is first refactored to
fixed-size NumPy arrays (`board: uint8[R,C]`, `boxes: uint16[N,2]`).
After that refactor, CPython alone is faster; Numba adds another 3–5×
on top. So you pay the full refactor cost for a 3–5× marginal win.

**Verdict:** Skip. The refactor cost approaches Option 3.7 (Rust/PyO3)
without the matching headline speedup.

### 3.6 Cython (considered and rejected for this codebase)

Cython adds type annotations to `.pyx` files and compiles to C.

**Why it's dominated:** Best use case here is a small `solver_hot.pyx`
for the BFS inner loop. But to avoid the Python/C boundary overhead
inside the loop, you'd inline the move function — which means a second
source of truth for every mechanic. PyPy achieves comparable speedup
without that cost. Rust/PyO3 achieves a bigger speedup with the same
cost. Cython sits in the middle with no unique advantage.

**Verdict:** Skip unless you specifically need `pip install` with no
PyPy runtime dependency AND can't justify Rust.

### 3.7 Rust + PyO3 / maturin  ⚠️ Biggest lever, biggest architectural cost

| Aspect | Assessment |
|--------|------------|
| Expected speedup | 20–50× over CPython |
| Effort | 600–1000 lines of Rust + build infra |
| Dependency cost | **Two implementations** of every game mechanic |

**Pros:** Near-C inner loop. Rust `HashSet` with custom hashers
outperforms CPython dict. Cache locality wins on dense array-backed
state. The 2.73 s colored demo would finish in ~100 ms; a 125 s
puzzle would finish in ~5 s.

**Cons, and this is the big one:** You must port every engine
mechanic to Rust — classic push, slab/laser/key/gate semantics,
portal teleport, switch latching, colored-box identity, color-aware
is_solved. Any future mechanic lands in both places. A bug fixed in
Python doesn't flow to Rust until someone notices. Plus ongoing build
matrix: prebuilt wheels for 3 OSes × 3 Python versions, or users need
a Rust toolchain installed.

**Verdict:** Worth it **only** if the solver becomes the product —
e.g. a level-difficulty analysis tool pumping thousands of levels
through the solver in batch. For an interactive editor where the
solver runs 1–5× per session, the two-implementations tax outweighs
the speedup.

**When:** After §3.1 + §3.2 + §3.3 + §3.4 are all in place and the
workload profile has genuinely shifted to large-batch solving.

### 3.8 Multi-core parallelism

The user explicitly set this aside. Recorded for completeness.

- **Threads don't help** for a single-puzzle search: CPython's GIL
  serializes every dict insert and heap push.
- **Processes** help for embarrassingly-parallel workloads (batch
  analysis of many levels) but add IPC overhead for a single puzzle.
- **Parallel portfolio** (running BFS + A* + macro-solver concurrently
  and accepting the first result) gives 1.5–3× on hard puzzles and
  composes with everything above.

### 3.9 Quick-reference decision matrix

```
I want the solver to feel faster in the editor.
  └─► §3.3 (thread the editor call)  +  §3.1 (parent pointers)

I want 3-5× overall speedup, no new deps, no runtime changes.
  └─► §3.1 (algorithmic wins)

I want 10-30× overall speedup, minimal code changes, opt-in install.
  └─► §3.1 + §3.2 (PyPy subprocess)

I want to solve levels that currently time out.
  └─► §3.1 + §3.4 (bitmask) + §3.7 (Rust) in that order
      Stop as soon as it's fast enough.

I want a published library solving thousands of levels per batch.
  └─► §3.7 (Rust/PyO3). Accept the two-implementation cost.
```

---

## 4. Beyond the solver — other roadmap items

### 4.1 Modularize `src/game.py`

Currently ~2,800 lines, one file. Splitting into `src/views/`,
`src/rendering.py`, `src/layout.py`, etc., would pay off in maintenance
the next time someone needs to touch it. Discussed in REVIEW.md §2.1.

### 4.2 Harder built-in levels

Genuine puzzle-design work: existing classic levels solve in well under
a second. Need hand-crafted levels that combine mechanics (e.g. a
colored box that must be pushed through a laser corridor, requiring
slab setup AND color matching AND portal shortcut). Attempted in an
earlier turn; hex-geometry math and solvability verification make this
non-trivial to do in bulk.

### 4.3 `HexLayout` extraction

`_calc_layout` + `_cell_xy` appears in 4 views. Extract once. Discussed
in REVIEW.md §2.2.

### 4.4 Engine save/restore public API

`_snapshot` / `_restore` are leading-underscore but used from outside
the engine (the solver). Either rename to remove the underscore or add
a thin public wrapper. Discussed in REVIEW.md §2.6.

### 4.5 Precomputed slab-position index in the engine

Currently `_slab_pressed` scans the full grid on every call. Cache
slab positions by group at `load_from_lines` time — benefits
gameplay AND the solver. Discussed in REVIEW.md §2.7.

---

## 5. Priority-ordered "next sprint"

If I had one week and wanted to maximize perceived quality:

1. **Thread the editor `Solve` / `Analyze`** (§3.3) — one afternoon,
   big UX win.
2. **Parent-pointer path reconstruction** (§3.1) — half a day, the
   single largest algorithmic win.
3. **Slab-position index** (§4.5) — one hour, helps gameplay and solver.
4. **Harder built-in levels** (§4.2) — iterative design work, 2–4 levels.
5. **HexLayout extraction** (§4.3) — one afternoon, enables future
   view splits.

That's ~3 days of work for a visibly better experience. Don't touch
Rust / PyPy / Numba until you've measured what's left after this.
