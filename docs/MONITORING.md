# Monitoring the Solver

Hexoban's solver can take anywhere from microseconds to minutes depending
on level complexity. This document covers how to **watch it work** and
**inspect what it did afterwards**.

---

## 1. Log file

Every run of Hexoban writes to `logs/hexoban.log` (relative to the
project root). The log is created on first use and rotated when it
exceeds ~1 MB — the previous contents move to `logs/hexoban.log.1`.

### What's in it

One line per event, timestamped to the second:

```
[14:22:11] Playing: 19. Hex Fortress (7x13, 4b)
[14:22:11] Solving: 4 boxes, 43 floor cells, grid 7x13
[14:22:11]   A*: push-distance heuristic (h0=12)
[14:22:11]   A* solved: 22m, 12,340 states, 0.03s
[14:22:14] LEVEL COMPLETE: 19. Hex Fortress in 47m 18p 03:21
[14:22:14]   NEW BEST! 47m (was 58m)
```

Useful fields to look for:

- `Solving: ... boxes, ... floor cells` — what the solver was handed.
- `Level uses extended tiles — dispatching to engine-driven BFS` —
  means the level has slabs/lasers/keys/gates/portals/colored boxes.
- `BFS solved: Nm, K states, Ts` — solve result and cost.
- `A* exhausted: K states in Ts` — the solver hit its budget without
  finding a solution (not necessarily unsolvable — see §4 below).
- `Macro-solver: SUCCESS!` or `FAILED` — per-box decomposition result.
- `LEVEL COMPLETE` — human solve.
- `NEW BEST!` — your move count beat any previously-saved solution.

### Rotation

When `hexoban.log` hits 1 MB it's renamed to `hexoban.log.1` and a fresh
file is started. Only one backup is kept; the second rotation
overwrites `hexoban.log.1`. If you want to preserve longer history,
copy `hexoban.log.1` aside before it gets replaced.

### Disabling

The log file is best-effort — any I/O failure (read-only filesystem,
no `logs/` permission, disk full) is silently swallowed so the game
keeps running. There's no config flag to disable it because it costs
essentially nothing; if you genuinely need to suppress it, make the
`logs/` directory a symlink to `/dev/null` on Linux/macOS or an
equivalent elsewhere.

---

## 2. Terminal progress bar

When the solver runs in a **TTY** (an interactive terminal, not a pipe
or file redirection), a live-updating progress bar appears on
standard error. It looks like:

```
[14:22:11] solve: [██████████··············]  42.3%    127,890 states |   2.14s |   59,762 st/s
```

Fields:

- `[HH:MM:SS]` — current time.
- `label` — which search stage is running (`solve`, `BFS`, `A*`, etc.).
- `[██···]` — progress toward the current stage's state budget.
- `XX.X%` — same thing as a percentage.
- `N states` — number of search states expanded so far.
- `T.Ts` — elapsed seconds in this stage.
- `N st/s` — current expansion rate (states per second). A healthy
  solver sustains 10k–100k st/s on CPython; a drop below 5k usually
  means memory pressure from deep paths or heap explosion.

The bar updates every 0.5 s during a solve. When the stage finishes,
the line is terminated with a newline so later log output appears below
it normally.

### When you won't see the bar

- **Piped or redirected output** (`python tools/benchmark.py > out.txt`).
  Carriage-return animation would clobber the file; the code detects
  `not isatty()` and silently suppresses the bar. You'll still get the
  regular one-line-per-event log in the file.
- **Running the GUI** (`python main.py`). The editor's `Solve` and
  `Analyze` buttons show an on-screen progress overlay instead.
- **Non-interactive shells** (IDE consoles that don't emulate a TTY).
  Same reason as piped output.

---

## 3. The benchmark tool

`tools/benchmark.py` is a small CLI for exercising the solver outside
the GUI. Use cases: verifying a level is solvable, benchmarking how
long it takes, regenerating the log with fresh solver traces.

### Invocations

```bash
# Solve every built-in level, print a summary table at the end
python tools/benchmark.py

# Solve specific built-ins by 1-indexed position
python tools/benchmark.py 19 20 25

# Solve a level file from disk
python tools/benchmark.py levels/custom4.json

# Mix of both
python tools/benchmark.py 26 levels/mylevel.json 27
```

### What it prints

Progress bars during each solve (TTY only), then a per-level summary:

```
Benchmark summary
------------------------------------------------------------------------------
  Level                             Boxes       Time    Moves   Pushes
------------------------------------------------------------------------------
  1. First Push                         1     0.00s         1         1
  27. Portal Switch Demo                1     0.00s         7         1
  28. Colored Boxes Demo                3     2.30s        12         6
------------------------------------------------------------------------------
  3/3 solved in 2.3s total
```

Exit code is `0` if all levels solved, `1` if any failed, `2` if the
arguments didn't resolve to any loadable levels.

The full solver trace (heuristic chosen, state counts, elapsed times)
goes to `logs/hexoban.log` in addition to the terminal.

---

## 4. Interpreting "no solution found"

When the solver returns `None`, there are three possible causes:

1. **The level is actually unsolvable.** Always possible, especially
   after editor changes. Run the level through the solver in the
   editor with `Solve` (`V` key) to confirm.
2. **The solver exhausted its state budget.** Default budgets: BFS
   1 M states, A* 3 M (initial) / 5 M (fallback), macro-solver 1 M
   per box, engine-driven BFS 500 K. Visible in the log as
   `... exhausted: K states in Ts`.
3. **A deadlock heuristic false-positive.** The corner-deadlock check
   only treats unconditionally-blocking tiles as blockers (walls,
   void). Lasers and closed gates are conditional and aren't counted.
   But if you've invented a custom deadlock mechanic in-engine, the
   heuristic may incorrectly prune — check the log for state counts
   that are suspiciously low relative to puzzle size.

If you suspect (2), the solver has no command-line flag to raise the
budget yet — edit the `max_states=` arguments in `src/resolver.py`'s
`solve()` function. If you suspect (3), bypass the classic cascade by
introducing an extended tile anywhere in the level (even a decorative
key with no gate) to force the engine-driven BFS path, which skips
the deadlock heuristic entirely.

---

## 5. Using the log file to tune difficulty

A quick recipe for calibrating a custom level's difficulty:

```bash
python tools/benchmark.py levels/mylevel.json
tail -5 logs/hexoban.log
```

Look at the `states` count in the `solved` line. Rough guide:

| States              | Classification |
|---------------------|----------------|
| ≤ 10                | Tutorial       |
| ≤ 500               | Easy           |
| ≤ 10,000            | Medium         |
| ≤ 100,000           | Hard           |
| > 100,000           | Extreme        |

The built-in levels were calibrated against these thresholds. Aim for
a blend across your level set rather than all at one tier.

---

## 6. FAQ

**Q: The progress bar shows `0 st/s` for several seconds at the start.**
A: That's the push-distance precompute in A*. It does a reverse-BFS
from every target before the main search starts. Expected on levels
with many targets; the bar begins updating once the main loop starts.

**Q: `states` keeps climbing forever but no solution comes.**
A: You've probably hit a budget-exhaust case (§4 above). Let it
finish — the solver will print the `exhausted` line and move to the
next strategy in the cascade, or return `None`.

**Q: Can I pause or cancel a solve?**
A: From the GUI, the `ResolverView` and (post-threading-fix, see
ROADMAP §3.3) `EditorView` will support a cancel button. From the
benchmark CLI, `Ctrl-C` interrupts the process cleanly; any partial
log entries are preserved.

**Q: The log file just keeps growing.**
A: It rotates at ~1 MB. If you see `hexoban.log.1` alongside
`hexoban.log`, rotation is working. If only `hexoban.log` exists and
it's much larger than 1 MB, rotation is failing silently — check
filesystem permissions on the `logs/` directory.
