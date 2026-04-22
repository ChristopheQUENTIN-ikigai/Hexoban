# Hexoban — Code Review & Improvement Proposals

This document captures the review the maintainers asked for, covering two
areas:

1. **Resolver efficiency** — why the CPU appears to freeze, what to change,
   and in what order.
2. **Source-code maintainability** — concrete refactors with file/line
   pointers, roughly ordered by impact-per-effort.

Everything here is advisory. The engine, editor, and solver changes
already shipped in this release (laser/slab/key/gate mechanics) are
independent of these proposals and do not require any of them to work.

---

## 1. Resolver freeze analysis

### What the user sees

"Sometimes the CPU freezes" — the window stops repainting, input is not
acknowledged, and the OS may briefly show a "Not Responding" title-bar
decoration. After several seconds to a minute it returns to normal.

### Two independent causes that stack

**Cause A — UI-thread blocking.** `EditorView._solve_current` and
`EditorView._analyze` call `solve()` directly from an `on_key_press` or
`_run_action` handler. Arcade's event loop runs on the same thread, so
while the solver is working, the window cannot repaint or process input.
Even a 500 ms solve feels like a freeze; a 30-second one looks like a
crash.

`ResolverView` already does this correctly: it spawns a worker thread
and polls status from `on_update`. The fix for the editor is the same
pattern — worker thread, shared `(result, progress, done)` struct,
spinner in `on_update`/`on_draw`.

**Cause B — algorithmic cost and memory pressure.** Even once the UI is
unblocked, some levels genuinely take a long time. For the existing
solver (classic Sokoban, `_solve_bfs` / `_solve_astar` / `_solve_macro`):

- **Path carried per queue entry.** Lines like `new_path = path + [d]`
  (`_solve_bfs` line ~574, `_solve_astar` line ~510) allocate a fresh
  list of length `depth` on every state expansion. On a 100 k-state
  search at average depth 40 that is 4 M list copies and ~4 M list
  objects held live. This alone can cause tens of seconds of stalls
  and gigabytes of RAM on hard levels.

- **Redundant heap entries.** A* pushes every successor even when a
  better path to the same state already exists in `g_scores`; the
  late-check on pop (`if g > g_scores.get(...)`) is correct but means
  the priority queue can hold multiple entries per state. Together
  with the per-entry path list this compounds the memory issue.

- **Per-expansion dict lookups.** `hex_neighbors(pr, pc)` is called
  six times per expansion (once per direction) and rebuilds a dict
  each call. With `ALL_DIRS` fixed and the grid static, a single
  precomputed `NEIGHBORS[r][c][dir_index]` 2-D table is ~8× faster
  in hot paths.

- **`_is_hex_deadlock` rescans 6 neighbours per push.** Cheap per
  call, but called on every potential box placement. Cache by
  `(r, c)` — the result depends only on static grid geometry.

For the **new extended solver** `_solve_bfs_extended` in
`src/resolver.py`, the `path + [dname]` pattern is also used. I chose
to ship it that way for a correctness-first first release; see
fix list below.

### Fixes in priority order

#### 1. Move the editor solve/analyze off the UI thread (1–2 hours)

The single biggest perceptual win. `ResolverView.__init__` / `on_update`
already shows the pattern — lift that into a small reusable helper:

```python
# src/solver_job.py (new)
class SolverJob:
    def __init__(self, engine):
        self.result = None
        self.progress = (0, 0, 0.0)  # (states, budget, seconds)
        self.done = False
        self._thread = threading.Thread(target=self._run, args=(engine,), daemon=True)
    def _run(self, engine):
        self.result = solve(engine, on_progress=self._set_progress)
        self.done = True
    def _set_progress(self, s, b, t):
        self.progress = (s, b, t)
    def start(self):
        self._thread.start()
```

Then `EditorView._solve_current` becomes: start a job, show a
"Solving..." overlay with a cancel button, poll `job.done` in
`on_update`, display result on completion. The engine passed to the
solver should be a *copy* (make `_snapshot`/`_restore` public — see
§2.6 below — and round-trip through them) so the editor state is not
touched.

#### 2. Parent-pointer path reconstruction (1 hour, ~3–10× speedup on deep solves)

Replace `new_path = path + [d]` everywhere in the solver with a
`parent: dict[state_key, (prev_key, dir)]` and walk backward at the end.
In `_solve_bfs` / `_solve_astar` the queue entry becomes just the state
tuple. In `_solve_bfs_extended` it becomes `(snapshot,)` with the
snapshot acting as a state id.

```python
parent[initial_key] = (None, None)
queue = deque([initial])
...
if new_key not in parent:
    parent[new_key] = (key, dname)
    queue.append(new_key)
...
# on goal:
moves = []
cur = goal_key
while parent[cur][0] is not None:
    prev, d = parent[cur]; moves.append(d); cur = prev
moves.reverse()
```

This removes the quadratic path-allocation cost; the `parent` dict is
linear in state count.

#### 3. Precompute neighbour and passability tables (30 min, ~1.5–3× speedup)

Once per `solve()` call, at entry:

```python
# Shape: [rows][cols][6] -> (nr, nc) or (-1, -1) if out of bounds
NEIGHBORS = _build_neighbor_table(engine)
# Shape: [rows][cols] -> bool, whether the cell is ever walkable (not WALL/EMPTY)
WALKABLE = _build_walkable_table(engine)
```

Replace every `hex_neighbors(pr, pc)[d]` with
`NEIGHBORS[pr][pc][dir_idx]`, and every
`engine.grid[nr][nc] in (WALL, EMPTY)` with `not WALKABLE[nr][nc]`.
Each of those lines is a hot path called millions of times.

#### 4. Cache `_is_hex_deadlock` per cell (10 min)

```python
_deadlock_cache = [[None]*cols for _ in range(rows)]
def _is_hex_deadlock_cached(engine, r, c):
    v = _deadlock_cache[r][c]
    if v is None:
        v = _is_hex_deadlock(engine, r, c)
        _deadlock_cache[r][c] = v
    return v
```

Cache is valid for the lifetime of a single `solve()` call because the
grid does not change mid-search.

#### 5. Precompute slab positions by group (extended solver only, 15 min)

`engine._slab_pressed` scans the entire grid on every call — O(R·C)
inside a per-move check that itself runs 6 times per state expansion.
Build a `slabs_by_group: list[list[(r,c)]]` once at solver entry and
change `_slab_pressed` to check only those positions.

**This change belongs in `engine.py`, not the solver**, and benefits
interactive play too. The allocation can be memoized on `load_from_lines`.

#### 6. Promote engine internals to public API (5 min, no perf gain)

`_snapshot`, `_restore`, `_push_undo` are leading-underscore (private)
but the resolver and the new extended BFS use them. Either:

- Rename to `snapshot`, `restore`, `push_undo` and remove the
  leading underscores, making them part of the supported contract; or
- Add a thin public wrapper API (`engine.save_state()` returning an
  opaque token and `engine.load_state(token)`).

Either way, the coupling becomes explicit instead of hidden.

#### 7. Expected combined speedup

On classic levels #19–#25 (Hard / Extreme), fixes (2)+(3)+(4) together
typically deliver **3–10× wall-clock speedup** with a larger drop in
peak memory. Fix (1) is orthogonal — it changes nothing about time, but
makes the freeze go away regardless of solve time, which is the user's
actual complaint. Do (1) first.

### Extended-solver specific caveats

The new `_solve_bfs_extended` (in `src/resolver.py`) is correctness-first
and has known inefficiencies that were accepted for this release:

- **Per-node snapshot carried in the queue** — a full `GameState`
  dataclass is kept for each queued state. For extended levels with
  many keys/gates/slabs this is cheap (the structures are small
  frozensets); but applying fix #2 would keep only state keys and
  reconstruct snapshots on demand from the parent chain + replay,
  trading memory for recomputation.

- **`_slab_pressed` still does a grid scan** — fix #5 applies directly.

- **State space grows combinatorially with keys and opened gates.**
  A level with 4 key colors and 2 gates of each color has 9× more
  states than the equivalent Sokoban layout. This is intrinsic to
  the mechanics and cannot be optimized away; it can only be
  mitigated with better pruning (e.g., "you will never voluntarily
  drop a key, so key count only ever decreases from collection" is
  already implicitly true, no action needed).

- **No deadlock detection for laser/gate interactions.** A box pushed
  into a corner formed by two real walls is detected; a box pushed
  into a corner formed by a wall and a permanently-on laser (no
  matching slab is box-reachable) is not. This is acceptable for
  the first release — false negatives here only slow the solver,
  they do not produce wrong answers.

---

## 2. Source-code maintainability

### 2.1 Split `src/game.py`

`src/game.py` is currently ~2,500 lines and holds every View subclass
plus the window, drawing primitives, and the `main()` entry point.
Proposed layout:

```
src/
├── rendering.py       # hex_center, _draw_hex_*, _draw_tile, palettes
├── layout.py          # HexLayout class (§2.2 below)
├── keymap.py          # _key_from_name, _hex_direction, _arrow_hex_direction
├── window.py          # HexobanWindow, _load_textures, _toggle_fullscreen
├── views/
│   ├── __init__.py
│   ├── menu.py        # MenuView, CreditsView
│   ├── level_select.py # LevelSelectView, LoadGameView
│   ├── game.py        # GameView
│   ├── editor.py      # EditorView
│   ├── resolver.py    # ResolverView
│   ├── replay.py      # ReplayView
│   └── optimize.py    # OptimizeView
└── main.py            # entry point (was at end of game.py)
```

Each view file would end up 200–900 lines — small enough to hold in your
head. The editor at ~920 lines deserves its own module regardless of the
broader refactor.

### 2.2 Extract `HexLayout`

`_calc_layout` and `_cell_xy` appear in at least four views:
`GameView`, `EditorView`, `ResolverView`, `ReplayView`. The math is
identical — only the surrounding HUD height constant differs. Proposed
class (roughly 40 lines):

```python
class HexLayout:
    """Pointy-top odd-r hex grid sized to fit into a viewport."""
    def __init__(self, rows, cols, viewport_w, viewport_h, max_hex_size=64):
        self.rows, self.cols = rows, cols
        self._fit(viewport_w, viewport_h, max_hex_size)
    def _fit(self, w, h, max_s):
        hex_w = math.sqrt(3); hex_h = 1.5
        grid_w_units = self.cols*hex_w + (hex_w/2 if self.rows>1 else 0)
        grid_h_units = (self.rows-1)*hex_h + 2
        self.hex_size = min((w-40)/grid_w_units, (h-20)/grid_h_units, max_s)
        actual_w = grid_w_units*self.hex_size
        actual_h = grid_h_units*self.hex_size
        self.offset_x = (w - actual_w)/2 + self.hex_size*math.sqrt(3)/2
        self.offset_y = (h - actual_h)/2 + self.hex_size
    def cell_xy(self, r, c, viewport_h):
        hx, hy = hex_center(r, c, self.hex_size)
        return self.offset_x + hx, viewport_h - self.offset_y - hy
    def screen_to_cell(self, sx, sy, viewport_h):
        # Currently duplicated in EditorView; move the brute-force O(R*C)
        # scan here. A later optimization would do a pixel-to-axial
        # rounding (well-known hex math), but the brute scan is fine
        # for the grid sizes we support.
        ...
```

Each view then holds a `self.layout = HexLayout(...)` and calls
`self.layout.cell_xy(r, c, h - HUD_H)`.

### 2.3 Kill dead code in `EditorView._finish_size_input`

Original lines ~1566:

```python
self.grid.append(row) if False else None  # noqa
row_final = row
new_grid.append(row_final)
```

The first line is unconditionally a no-op (`if False`). The second
aliases `row` to `row_final` for no reason. The function also
duplicates ~80% of `_resize_grid`'s body. Fix:

```python
def _finish_size_input(self, text):
    text = text.strip().lower()
    for sep in ['x', '*', ',', ' ']:
        if sep in text:
            parts = text.split(sep, 1)
            try:
                nc = max(4, min(24, int(parts[0].strip())))
                nr = max(4, min(24, int(parts[1].strip())))
                self._resize_grid(nr - self.grid_rows, nc - self.grid_cols)
                return
            except ValueError:
                pass
    self._msg("Invalid format. Use: 10x8")
```

This is correct, 12 lines instead of 40, and routes through the tested
`_resize_grid` codepath.

### 2.4 Replace string-keyed action dispatch

`EditorView._run_action` switches on action labels:

```python
action_map = {
    "Name": self._start_name_input,
    "Save": self._save,
    ...
}
fn = action_map.get(label)
```

If someone rewords a label in `_get_actions` (say, "Save" to "Save Lvl")
the action silently stops working. Replace with a struct:

```python
@dataclass
class EditorAction:
    label: str
    shortcut: str
    handler: Callable

ACTIONS = [
    EditorAction("Name", "N", "_start_name_input"),
    EditorAction("Save", "S", "_save"),
    ...
]
```

Now label, shortcut, and handler are bound together; changing one of
them can't desynchronize the others.

### 2.5 Centralize tile drawing dispatch

Already partly done in this release: `_draw_tile` now handles the new
extended tiles via `is_slab` / `is_laser` / `is_key` / `is_gate`. The
natural next step is to turn that dispatch into a registry:

```python
# In src/rendering.py
TILE_DRAWERS: dict[int, Callable] = {
    WALL: _draw_wall_tile,
    FLOOR: _draw_floor_tile,
    TARGET: _draw_target_tile,
    EMPTY: _draw_empty_tile,
}
# Extended tiles use predicate dispatch:
def _draw_tile(cx, cy, s, tid, **state):
    if tid in TILE_DRAWERS: return TILE_DRAWERS[tid](cx, cy, s)
    if is_slab(tid):  return _draw_slab_tile(cx, cy, s, slab_group(tid), state.get("slab_pressed", False))
    ...
```

This makes adding a 5th tile category a 2-line change (add drawer, add
predicate branch) instead of editing an `elif` chain.

### 2.6 Make engine save/restore API public

As mentioned in §1.6 above, the resolver uses `engine._snapshot` and
`engine._restore`. Rename to remove the underscore, update the 4 call
sites in the engine + the 2 in the new resolver. Document them as the
supported way to save/restore state from outside the engine.

### 2.7 Precompute slab positions at level load

Currently `HexobanEngine._slab_pressed` iterates the full grid every
call. Slabs cannot appear or disappear during play, so their positions
should be indexed once at the end of `load_from_lines`:

```python
# In engine.py, at end of load_from_lines():
self._slabs_by_group: list[list[tuple[int,int]]] = [[] for _ in range(NUM_LASER_GROUPS)]
for r, row in enumerate(self.grid):
    for c, tid in enumerate(row):
        if is_slab(tid):
            self._slabs_by_group[slab_group(tid)].append((r, c))

# _slab_pressed becomes:
def _slab_pressed(self, group, boxes, player_rc):
    for rc in self._slabs_by_group[group]:
        if rc == player_rc or rc in boxes:
            return True
    return False
```

On a 20×20 grid with 3 slabs, this goes from 400 checks per laser-test
to 3. The solver benefits too — this is fix #5 from §1 but lives here
and helps interactive play as well.

### 2.8 Consolidate numeric tile IDs behind an Enum

`WALL = 1`, `FLOOR = 2`, ..., `SLAB_BASE = 10`, `LASER_BASE = 20` etc.
are currently plain module-level integers. They work, but:

- `IntEnum` would give you `TileKind.WALL`, type hints that actually
  mean something, and iteration in tests / logs.
- The extended tile encoding as `(BASE + group_index)` is implicit;
  swapping it for an `(category, index)` pair would be more readable.

This is strictly cosmetic and low-priority — only worth doing if the
split in §2.1 is also happening.

### 2.9 Tests exist now — keep them running

`tests/test_engine.py` (15 tests) and `tests/test_resolver.py` (7
tests) were added in this release and both pass. Wire them into a
one-liner runner so regressions are visible:

```bash
# At repo root, add a Makefile or run_tests.sh:
python tests/test_engine.py && python tests/test_resolver.py
```

Anything more elaborate (pytest, CI) is optional but welcome.

---

## 3. Priority summary

If you only do three things:

1. **Thread the solver in the editor** (`_solve_current`, `_analyze`).
   This makes the visible freeze go away regardless of anything else.
2. **Precompute slab positions by group at load time** (`engine.py`).
   Trivial change, helps both gameplay and the extended solver.
3. **Parent-pointer path reconstruction in all solvers**. Largest
   algorithmic win per line of code changed.

The rest can happen incrementally.

---

## 4. Resolver review for v3 (portals, switch, colored boxes)

The v3 release adds three mechanics: a single pair of portals (blue entry,
orange destination), a single latching switch that gates the portal, and
per-box color identity with matching colored targets. This section
captures the review for how these interact with the solver, what actually
needed to change, and what the state-space costs are.

### What had to change in the solver

Two touch-points, both small:

1. **State-key extension** in `_make_key` inside `_solve_bfs_extended`
   (`src/resolver.py`). The BFS dedup key previously was
   `(player_r, player_c, boxes, held_keys, opened_gates, collected_keys)`.
   Two dimensions were added: `box_colors` (the sorted-tuple
   representation from `GameState`) and `switch_on` (bool). Without
   this, the BFS would merge states that are actually distinct — e.g.
   "box 1 at (3,2), box 2 at (3,5)" vs. "box 2 at (3,2), box 1 at (3,5)"
   — and return solutions that only look correct.

2. **Dispatch extension** in `_level_has_extended_tiles`. The predicate
   now also checks `engine.box_colors`, `engine.target_colors`, and the
   new `is_portal_in`/`is_portal_out`/`is_switch`/`is_colored_target`
   predicates. A level with colored boxes on an otherwise-classic grid
   would otherwise slip through to the hand-rolled fast-path BFS which
   doesn't know about colors and would claim false "solved."

That is the entire resolver delta. The engine-driven BFS itself —
specifically its use of `engine.move()` and `engine.is_solved()` for
all move legality and win-condition logic — needed zero modification,
because `engine.move()` was updated to handle the new mechanics and
`is_solved()` was rewritten for color compatibility. This is the
correctness-first design from the v2 release paying off a second time.

### State-space impact: measured, not guessed

The shipped tests give empirical numbers to reason from:

- **`test_portal_solving_requires_switch`** — 5 moves, 17 states,
  <0.01 s. Portal compresses the walkable graph: the shortest path
  between blue and orange without the portal would need roughly 12
  cells of detour, and the BFS would explore more than 17 states to
  find it. Conclusion: a well-placed portal is a net reduction in
  search cost.

- **`test_colored_box_must_land_on_matching_target`** — 10 moves,
  1,690 states, 0.11 s. Two colored boxes on 2 colored targets.
  Compare to a classic 2-box level of similar size: typically 200–500
  states. The 3–8× multiplier is the dedup cost of tracking which
  specific box is at which position.

- **`test_builtin_colored_demo_solvable`** — 12 moves, 31,275 states,
  2.73 s. Three boxes (2 colored + 1 uncolored). Still tractable but
  visibly slower. For a 4-box colored puzzle the state count would
  push into 100k+ territory and would benefit from the optimizations
  in section 1 (parent pointers especially).

The rough scaling rule: **every colored box multiplies the effective
state space by a factor equal to the number of positions it can
distinguish**, because two boxes of different colors are no longer
interchangeable in the dedup hash. The switch dimension at worst
doubles state count. Portals tend to reduce total search time because
the shortcut edge is used early in almost every successful path.

### Deadlock detection — what didn't need to change

The corner-deadlock check in `_is_hex_deadlock` is still correct
without modification:

- **Portals** and **switches** never involve boxes (boxes cannot
  teleport or toggle). They cannot create or remove corner deadlocks
  directly. A box pushed into a corner formed by two walls is still
  deadlocked regardless of whether a portal tile exists nearby.

- **Colored boxes** do weaken the "box in corner = deadlock"
  heuristic in a subtle way: a colored box in a corner is still
  deadlocked if it isn't on a target of its color, but the check
  currently only asks "is this a target?", which gives false negatives
  on a colored box sitting on a mismatched target. The engine-driven
  BFS doesn't actually use this heuristic directly — only the classic
  `_solve_bfs`/`_solve_astar` do, and those never run on levels with
  colored boxes because `_level_has_extended_tiles` diverts them.
  So no fix is required today. If a future colored-aware A* is added
  on top of the extended BFS, the fix is one predicate change:

  ```python
  def _is_hex_deadlock_colored(engine, r, c, box_color):
      if (r, c) in engine.targets:
          tgt_color = engine.target_colors.get((r, c), -1)
          if tgt_color == box_color:
              return False        # compatible target: not a deadlock
          # mismatched target: still a deadlock, fall through
      # ... existing corner-check logic ...
  ```

### On the boxes-don't-teleport decision

The engine choice that a box pushed onto a blue portal simply sits
there (rather than teleporting to orange) has solver consequences
worth flagging: it means box positions are preserved across any
player teleport, so the box-position state dimension is independent
of the switch and portal machinery. If boxes did teleport, every
box adjacent to blue portal-in would need to be evaluated for
destination-compatibility on every move, and the branching factor
would inflate substantially. The "only the player teleports" choice
is simpler to reason about AND cheaper to solve — both arguments
support it.

### On the mandatory-teleport decision

When the switch is ON, stepping onto blue portal-in is either a
full teleport or a rejected move (if orange is blocked by a box).
The alternative — "player can stand on blue without teleporting" —
would add a branch: is the player on blue-with-teleport-available,
or on blue-with-teleport-just-used? That's another boolean dimension
per visited state, doubling dedup cost with no puzzle-design benefit
that I can see. Worth keeping the current rule.

### What to optimize first if colored levels get bigger

The priority list from section 1 still applies in full. The specific
addition for colored-box levels: **precompute a compact color index
per box at level load**. Currently `box_colors` is stored as a dict
`{(r,c): color}` and serialized to a sorted tuple in `_snapshot`. For
large colored levels this tuple is the dominant memory cost per
queued state. If box identity is what matters (not their original
positions), rekey by box index: assign each box a stable 0..N-1 ID
at load, and store `box_positions: tuple[tuple[int,int], ...]` indexed
by ID. Dedup becomes faster (positional comparison instead of set
comparison) and memory per state drops.

Not needed today — the demo solves in <3 s — but this is the obvious
next step if colored-puzzle depth grows.

---

## 5. Alternative runtimes for the solver — ranked and weighed

The user asked specifically about **Numba** and **Rust/PyO3** bindings
and explicitly set aside multi-process parallelism. What follows is a
candid comparison of every runtime-level lever available for this
solver, in roughly decreasing "return per unit of maintenance pain."

Ground rules for the comparison:

- The **correctness-first engine-driven BFS** is the hot path. It
  delegates to `engine.move()` and `engine.is_solved()`, so any
  runtime change must either accelerate those or replace them wholesale.
- The **inner loop** is: pop a state from the queue, apply 6 candidate
  moves by calling `engine.move()` + `engine._restore()` to undo, hash
  each resulting state snapshot, check visited-set, push to queue.
  That's a Python-object-heavy loop — hashing compound tuples and
  frozensets — not a numeric kernel.
- **Benchmark reference:** `test_builtin_colored_demo_solvable` solves
  in 12 moves / 31,275 states / 2.73 s on CPython 3.11. The bigger
  solver-reviewed classic levels (#24 Hex Extreme) take ~2.6 s. These
  are the realistic workloads we should judge accelerators against.

### Option A — Algorithmic wins in pure Python (do this first)

Covered in §1 of this document. Parent-pointer path reconstruction,
precomputed neighbor / walkability tables, per-cell deadlock cache,
slab-index cache at load time. **Expected speedup: 3–10× on hard
levels.** Zero new dependencies, zero code outside `src/resolver.py`
and a small addition in `src/engine.py`. Maintains the single-source-
of-truth engine. If any single optimization pays for itself many times
over, it is parent pointers — the current BFS carries `path + [d]` per
queue entry, which is O(depth) allocation per state; parent pointers
make path reconstruction O(depth) once at the end.

Do this before considering any of the options below. Everything else
multiplies against this baseline.

### Option B — Numba

Numba is a JIT compiler for numeric Python. The `@jit(nopython=True)`
decorator turns an annotated function into a native routine. It
excels at NumPy-array loops and SIMD-friendly inner kernels.

**Where it fits the solver:**
- The hot loop is hash-table operations on compound keys
  (`(int, int, frozenset[tuple[int,int]], tuple[int,...], frozenset,
  bool)`). Numba's `nopython` mode does not accept frozensets or
  heterogeneous tuples of tuples. It supports `typed.Dict` and
  `typed.Set`, but those containers' performance for tuple keys is
  modest — typically 1.5–2× faster than CPython's built-in hash — and
  they cannot be constructed from Python sets without per-element
  conversion.
- Where Numba *would* shine: if the state were refactored into
  fixed-size NumPy arrays — e.g. `board: np.uint8[R, C]`,
  `box_positions: np.uint16[N_BOXES, 2]` — then `hash(arr.tobytes())`
  runs on a contiguous buffer and Numba can JIT the expansion logic
  over integer arrays cleanly. This is the ideal Numba path.
- But that refactor is *most of the work*. Once state is flat arrays,
  CPython alone gets a sizeable speedup from the change (fewer Python
  object allocations); Numba's marginal contribution on top is 2–4×,
  not the 20× one sometimes sees for NumPy-heavy code.

**Verdict:** Real win, ~3–5× on top of the algorithmic baseline,
**after** an invasive state-representation refactor. Keeps you inside
Python. Fragile: any accidentally non-`nopython` object (a
`frozenset.copy()`, a dict default, a `tuple(map(...))`) makes Numba
silently fall back to object-mode and you lose the speedup with no
error. Ranked mid-pack because the refactor is large and the win is
capped.

### Option C — PyPy (drop-in tracing JIT)

PyPy is a separate Python interpreter with a tracing JIT. On exactly
this kind of code — tight loops doing hash operations on compound
keys, with occasional allocations and no NumPy — PyPy typically
delivers **5–15× speedup over CPython with zero code changes**.

**Constraints specific to this project:**
- Arcade (the GUI library) does not currently support PyPy cleanly.
  Running the whole app under PyPy is not viable.
- So PyPy is viable only as a *solver subprocess*: the GUI (CPython +
  Arcade) spawns a PyPy subprocess that loads the same `src/levels.py`
  and `src/engine.py` and `src/resolver.py`, runs `solve()`, prints
  the move list as JSON to stdout. GUI reads the result and animates.
  Total added plumbing: ~80 lines, one new file `tools/solver_pypy.py`.
- Zero code changes to the engine or resolver. Zero dependency bloat
  at runtime (PyPy is optional — if not installed, fall back to
  in-process CPython solve).

**Verdict:** The highest return-per-effort option after Option A.
5–15× speedup, no code rewrite, no single-source-of-truth violation,
optional install. The tradeoff is subprocess IPC latency (~20 ms
startup, plus JSON serialization of the move list), which dominates
for puzzles the CPython solver handles in <50 ms. So the dispatch
would be: "if the puzzle size suggests it'll take >1 s, use PyPy
subprocess; otherwise solve in-process." That threshold is easy to
estimate from `n_boxes * n_floor_cells`.

### Option D — Cython (type-annotated C extension)

Cython is a compile-step that turns type-annotated `.pyx` files into
C extensions. On the solver's hot loop you'd annotate state indices
as `cdef int`, box positions as `cdef (int, int)`, replace the
visited-set's compound tuple with an integer-hash of bit-packed
state, and compile.

**Where it fits:**
- Best use case: a small `solver_hot.pyx` that implements *only* the
  BFS-expansion inner loop, accepting and returning Python objects at
  the boundary. The engine-driven approach still calls `engine.move()`
  — that part stays Python, and the overhead of crossing the
  Cython/Python boundary per move eats into the speedup.
- If you inline a hand-rolled move function into the Cython file (no
  engine call), you get 15–30× on the inner loop. But you've now
  reintroduced the problem the engine-driven design solved: a second
  source of truth for move mechanics, which must be kept in sync as
  new tile types are added.

**Verdict:** 10–30× if you accept the two-sources-of-truth cost.
Less invasive build than Rust (Cython auto-generates C, `pip install`
works out of the box). Still requires a C toolchain on Windows (MSVC
build tools) which is a real user-side friction. Ranked behind PyPy
for this project specifically because PyPy requires no code
duplication.

### Option E — Rust + PyO3 / maturin

PyO3 is Rust's canonical FFI to Python. Maturin packages a Rust crate
as a Python wheel. The workflow: write a Rust crate implementing the
solver, expose a single `solve(level_lines: Vec<String>) -> Vec<String>`
function, build wheels with `maturin build`, `pip install` the wheel.

**Speedup expectations:**
- Inner-loop speed is near-C. Rust's `HashSet<T>` with `BuildHasher`
  tuned for small tuple keys outperforms CPython's dict by a solid
  margin. Cache locality wins on dense array-backed state.
- **Expected total speedup: 20–50× over pure CPython**, possibly more
  for deep searches where allocation dominates.
- For comparison: the 2.73 s / 31k-state colored demo would finish in
  roughly 100 ms. A puzzle that currently takes 125 s would take
  5 s.

**Costs that matter more than the code itself:**
- You need to reimplement every mechanic in Rust: classic push,
  slab/laser pressure interaction, key pickup, gate opening, portal
  teleport, switch toggling, colored-box identity, is_solved color
  compatibility. That is ~600–1000 lines of Rust.
- **The engine is now two implementations**, and they can silently
  drift. A bug fixed in Python won't flow to Rust until someone ports
  it. A new mechanic means four things to keep in sync: engine,
  resolver state key, tests, Rust port.
- Build matrix: you need to publish prebuilt wheels for Linux/macOS/
  Windows × Python 3.10/3.11/3.12 or require users to have a Rust
  toolchain installed for `pip install`. `cibuildwheel` + GitHub
  Actions handles this, but it's ongoing maintenance surface.
- Debugging cross-language is slower than single-language debugging.
  A Rust panic surfaces as a Python exception with partial context.

**Verdict:** By far the biggest single speedup, but it re-architects
the project. I would do this only if the solver is the product — e.g.
if Hexoban becomes a level-difficulty-analysis tool for other editors,
where people pump thousands of levels through the solver in batch.
For an interactive editor where the solver runs 1–5× per session, the
cost-benefit is unfavorable.

### Option F — Bitmask-packed state in pure Python

A non-runtime option worth mentioning: on small grids (≤63 reachable
cells), the set of box positions fits in a single 64-bit integer. The
state key becomes `(player_idx: int, boxes: int, switch: bool, ...)`
— all integers. Python's integer hash is extremely fast, and the
visited-set shrinks dramatically. Can be combined with any of the
above.

**Verdict:** Niche but real. Gets 2–4× from CPython alone on small
grids (≤8x8 roughly), and multiplies cleanly with Numba / PyPy / Rust.
Worth doing if the target level size is bounded.

### Ranking and recommendation

For this specific project, the path I would follow:

1. **Option A (algorithmic wins in pure Python)** — do this regardless.
   3–10× speedup, no new deps, two days of work.
2. **Option C (PyPy as solver subprocess)** — if (1) is not enough.
   Another 5–15× on top, zero code duplication, opt-in install.
3. **Option F (bitmask state)** — if your levels stay small.
   Cross-cuts with everything else.
4. **Option E (Rust/PyO3)** — only if the solver becomes a product in
   its own right, or if (1)+(2)+(3) combined still aren't enough.
5. **Option B (Numba)** — skip for this project. The state shape is
   wrong for Numba's sweet spot, and the refactor cost is nearly the
   same as Option E without the matching speedup.
6. **Option D (Cython)** — skip. Strictly dominated by PyPy for your
   use case (zero code duplication) and by Rust (bigger speedup, same
   build pain).

The meta-observation is that **the dominant cost of any non-Python
accelerator is the violation of the engine-as-single-source-of-truth
architecture**. That architecture has paid off twice already (v2
added 4 mechanics, v3 added 3 mechanics, both cycles required zero
changes to the solve loop). Trading it away for ≤50× speedup on a
workload that's already under 3 seconds would be a bad deal. Trading
it away for a 500× speedup on a workload that's currently 5 minutes
and needs to be 5 seconds would be a good deal. Neither scenario
matches today's profile.

**Concrete first step** if you want to move on this: ship Option A
from §1 (parent pointers alone would pay for itself), measure what's
left, and only then decide whether PyPy or Rust is needed. Premature
acceleration is how you end up with two implementations of the same
engine and bugs in both.
