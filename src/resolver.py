"""Hexoban solver — macro-solver (per-box) + A* + BFS.

Solver hierarchy:
1. BFS for trivial puzzles (1 box or ≤30 floor cells)
2. A* with push-distance heuristic for medium puzzles
3. Macro-solver for large/complex puzzles: solves one box at a time,
   treating already-placed boxes as obstacles. This mimics how humans
   solve Sokoban — not optimal but tractable on large open maps.
4. Falls back up the chain if a method fails.

The macro-solver works by:
  a) Computing optimal box→target assignment (Hungarian-like greedy by push distance)
  b) For each box in order (closest to target first):
     - Use A* to find moves that push THIS box to its target
     - Other boxes are treated as immovable walls
     - Once placed, treat it as a wall for subsequent boxes
  c) Concatenate all move sequences
"""
from __future__ import annotations

import heapq
import time
from typing import Optional, Callable
from collections import deque

from src.engine import HexobanEngine, WALL, EMPTY
from src.levels import (
    hex_neighbors, FLOOR, TARGET,
    is_slab, is_laser, is_key, is_gate,
    is_portal_in, is_portal_out, is_switch, is_colored_target,
    is_crumble, is_radioactive, is_cbrn_item,
    NUM_KEY_COLORS,
)
from src.solutions import log

ALL_DIRS = ["TOP_LEFT", "TOP_RIGHT", "LEFT", "RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT"]
OPPOSITE = {
    "TOP_LEFT": "BOTTOM_RIGHT", "TOP_RIGHT": "BOTTOM_LEFT",
    "LEFT": "RIGHT", "RIGHT": "LEFT",
    "BOTTOM_LEFT": "TOP_RIGHT", "BOTTOM_RIGHT": "TOP_LEFT",
}


def _offset_to_cube(r: int, c: int):
    x = c - (r - (r & 1)) // 2
    z = r
    y = -x - z
    return x, y, z


def hex_distance(r1: int, c1: int, r2: int, c2: int) -> int:
    x1, y1, z1 = _offset_to_cube(r1, c1)
    x2, y2, z2 = _offset_to_cube(r2, c2)
    return (abs(x1 - x2) + abs(y1 - y2) + abs(z1 - z2)) // 2


# ═══════════════════════════════════════════════════════════════════
# Push-distance precomputation
# ═══════════════════════════════════════════════════════════════════

def _compute_push_distances(engine: HexobanEngine):
    """Precompute minimum pushes from every cell to every target (ignoring other boxes)."""
    rows, cols = engine.rows, engine.cols
    result = {}
    for tr, tc in engine.targets:
        dist = {(tr, tc): 0}
        queue = deque([(tr, tc, 0)])
        while queue:
            br, bc, d = queue.popleft()
            for push_dir in ALL_DIRS:
                opp = OPPOSITE[push_dir]
                nbs_box = hex_neighbors(br, bc)
                prev_r, prev_c = nbs_box[opp]
                if not (0 <= prev_r < rows and 0 <= prev_c < cols):
                    continue
                if engine.grid[prev_r][prev_c] in (WALL, EMPTY):
                    continue
                nbs_prev = hex_neighbors(prev_r, prev_c)
                player_r, player_c = nbs_prev[opp]
                if not (0 <= player_r < rows and 0 <= player_c < cols):
                    continue
                if engine.grid[player_r][player_c] in (WALL, EMPTY):
                    continue
                if (prev_r, prev_c) not in dist or dist[(prev_r, prev_c)] > d + 1:
                    dist[(prev_r, prev_c)] = d + 1
                    queue.append((prev_r, prev_c, d + 1))
        result[(tr, tc)] = dist
    return result


# ═══════════════════════════════════════════════════════════════════
# Heuristics
# ═══════════════════════════════════════════════════════════════════

def _heuristic_push(boxes, push_dists, targets):
    if not boxes or not targets:
        return 0
    box_list = list(boxes)
    target_list = list(targets)
    used = [False] * len(target_list)
    total = 0
    for br, bc in box_list:
        best_dist, best_j = 999999, 0
        for j, (tr, tc) in enumerate(target_list):
            if not used[j]:
                d = push_dists.get((tr, tc), {}).get((br, bc), None)
                if d is None:
                    # Fallback to hex distance if push-distance unreachable
                    d = hex_distance(br, bc, tr, tc) * 2
                if d < best_dist:
                    best_dist, best_j = d, j
        used[best_j] = True
        total += min(best_dist, 200)  # cap to keep heuristic admissible-ish
    return total


def _heuristic_simple(boxes, targets):
    if not boxes or not targets:
        return 0
    box_list = list(boxes)
    target_list = list(targets)
    used = [False] * len(target_list)
    total = 0
    for br, bc in box_list:
        best_dist, best_j = 999999, 0
        for j, (tr, tc) in enumerate(target_list):
            if not used[j]:
                d = hex_distance(br, bc, tr, tc)
                if d < best_dist:
                    best_dist, best_j = d, j
        used[best_j] = True
        total += best_dist
    return total


# ═══════════════════════════════════════════════════════════════════
# Deadlock detection
# ═══════════════════════════════════════════════════════════════════

def _is_hex_deadlock(engine, r, c):
    """3+ consecutive blocked directions = corner deadlock.

    Only unconditionally-blocking tiles (walls and voids) count as
    blockers here. Lasers and closed gates are NOT counted as blockers
    because they are conditional: a laser can be disarmed by pressing a
    slab, and a gate can be opened by collecting the matching key. A box
    that appears cornered by these tiles may in fact be solvable later,
    so flagging it as a deadlock would incorrectly prune valid states.
    """
    if (r, c) in engine.targets:
        return False
    nbs = hex_neighbors(r, c)
    dirs = ["TOP_LEFT", "LEFT", "BOTTOM_LEFT", "BOTTOM_RIGHT", "RIGHT", "TOP_RIGHT"]
    blocked = []
    for d in dirs:
        nr, nc = nbs[d]
        blocked.append(not (0 <= nr < engine.rows and 0 <= nc < engine.cols)
                       or engine.grid[nr][nc] in (WALL, EMPTY))
    for i in range(6):
        if blocked[i] and blocked[(i+1)%6] and blocked[(i+2)%6]:
            return True
    return False


def _level_has_extended_tiles(engine) -> bool:
    """True if the level uses any tile or feature the hand-rolled classic
    solvers don't understand: slabs, lasers, keys, gates, portals, switch,
    colored targets, colored boxes, crumble, radioactive, or CBRN items."""
    if engine.box_colors or engine.target_colors:
        return True
    for row in engine.grid:
        for t in row:
            if (is_slab(t) or is_laser(t) or is_key(t) or is_gate(t)
                or is_portal_in(t) or is_portal_out(t) or is_switch(t)
                or is_colored_target(t)
                or is_crumble(t) or is_radioactive(t) or is_cbrn_item(t)):
                return True
    return False


# ═══════════════════════════════════════════════════════════════════
# Player reachability BFS (can player reach cell X given current boxes?)
# ═══════════════════════════════════════════════════════════════════

def _player_reachable(engine, pr, pc, obstacles, target_r, target_c):
    """BFS: can player walk from (pr,pc) to (target_r,target_c) avoiding obstacles?
    Returns the path as list of directions, or None.
    """
    if (pr, pc) == (target_r, target_c):
        return []
    visited = {(pr, pc)}
    queue = deque([(pr, pc, [])])
    while queue:
        r, c, path = queue.popleft()
        for d in ALL_DIRS:
            nbs = hex_neighbors(r, c)
            nr, nc = nbs[d]
            if not (0 <= nr < engine.rows and 0 <= nc < engine.cols):
                continue
            if engine.grid[nr][nc] in (WALL, EMPTY):
                continue
            if (nr, nc) in obstacles:
                continue
            if (nr, nc) in visited:
                continue
            visited.add((nr, nc))
            new_path = path + [d]
            if (nr, nc) == (target_r, target_c):
                return new_path
            queue.append((nr, nc, new_path))
    return None


# ═══════════════════════════════════════════════════════════════════
# MACRO-SOLVER: solve one box at a time
# ═══════════════════════════════════════════════════════════════════

def _solve_single_box_astar(engine, player_r, player_c, box_r, box_c, 
                             target_r, target_c, obstacles, max_states=500_000):
    """Push one box from (box_r,box_c) to (target_r,target_c) using A*.
    
    State = (player_r, player_c, box_r, box_c)
    obstacles = frozenset of cells that act as walls (other boxes already placed)
    Returns list of move directions or None.
    """
    initial = (player_r, player_c, box_r, box_c)
    h0 = hex_distance(box_r, box_c, target_r, target_c)
    counter = 0
    open_set = [(h0, counter, initial, [])]
    g_scores = {initial: 0}
    states = 0
    
    while open_set and states < max_states:
        f, _, (pr, pc, br, bc), path = heapq.heappop(open_set)
        states += 1
        g = len(path)
        
        if g > g_scores.get((pr, pc, br, bc), float('inf')):
            continue
        
        # Win: box is on target
        if (br, bc) == (target_r, target_c):
            return path
        
        for d in ALL_DIRS:
            nbs_p = hex_neighbors(pr, pc)
            nr, nc = nbs_p[d]
            
            if not (0 <= nr < engine.rows and 0 <= nc < engine.cols):
                continue
            if engine.grid[nr][nc] in (WALL, EMPTY):
                continue
            if (nr, nc) in obstacles:
                continue
            
            new_br, new_bc = br, bc
            if (nr, nc) == (br, bc):
                # Pushing the box
                nbs_b = hex_neighbors(br, bc)
                nbr, nbc = nbs_b[d]
                if not (0 <= nbr < engine.rows and 0 <= nbc < engine.cols):
                    continue
                if engine.grid[nbr][nbc] in (WALL, EMPTY):
                    continue
                if (nbr, nbc) in obstacles:
                    continue
                new_br, new_bc = nbr, nbc
                # Deadlock check on new box position
                if (new_br, new_bc) != (target_r, target_c):
                    if _is_hex_deadlock(engine, new_br, new_bc):
                        continue
            
            new_state = (nr, nc, new_br, new_bc)
            new_g = g + 1
            if new_g >= g_scores.get(new_state, float('inf')):
                continue
            g_scores[new_state] = new_g
            
            h = hex_distance(new_br, new_bc, target_r, target_c)
            counter += 1
            heapq.heappush(open_set, (new_g + h, counter, new_state, path + [d]))
    
    return None


def _assign_boxes_to_targets(boxes, targets, push_dists):
    """Greedy assignment: closest box to closest target first.
    Returns list of (box_pos, target_pos) pairs in solve order.
    """
    remaining_boxes = list(boxes)
    remaining_targets = list(targets)
    assignments = []
    
    while remaining_boxes and remaining_targets:
        best_dist = 999999
        best_bi, best_ti = 0, 0
        for bi, (br, bc) in enumerate(remaining_boxes):
            for ti, (tr, tc) in enumerate(remaining_targets):
                d = push_dists.get((tr, tc), {}).get((br, bc), 999999)
                if d == 999999:
                    d = hex_distance(br, bc, tr, tc)
                if d < best_dist:
                    best_dist = d
                    best_bi, best_ti = bi, ti
        assignments.append((remaining_boxes[best_bi], remaining_targets[best_ti]))
        remaining_boxes.pop(best_bi)
        remaining_targets.pop(best_ti)
    
    return assignments


def _solve_macro(engine: HexobanEngine, max_states_per_box: int = 1_000_000,
                 on_progress: Optional[Callable] = None) -> Optional[list[str]]:
    """Macro-solver: solve one box at a time.
    
    Strategy:
    1. Assign each box to a target (greedy by push distance)
    2. For each (box, target) pair — closest first:
       a. Use A* to push just this one box to its target
       b. Other unplaced boxes + already-placed boxes are obstacles
       c. Once placed, the box becomes an obstacle
    3. Concatenate all move sequences
    
    This is not optimal but works on large open maps where full A* fails.
    """
    t_start = time.time()
    push_dists = _compute_push_distances(engine)
    
    # Assign boxes to targets
    assignments = _assign_boxes_to_targets(
        list(engine.boxes), list(engine.targets), push_dists)
    
    log(f"  Macro-solver: {len(assignments)} box→target assignments")
    for i, ((br, bc), (tr, tc)) in enumerate(assignments):
        d = push_dists.get((tr, tc), {}).get((br, bc), hex_distance(br, bc, tr, tc))
        log(f"    Box {i+1}: ({br},{bc}) → ({tr},{tc}) push-dist={d}")
    
    all_moves = []
    placed_boxes = set()      # boxes already on their targets (act as walls)
    current_boxes = set(engine.boxes)  # current positions of all boxes
    player_r, player_c = engine.player_r, engine.player_c
    total_states = 0
    
    # Try multiple orderings: original + reversed
    for attempt, ordering in enumerate([assignments, list(reversed(assignments))]):
        if attempt > 0:
            log(f"  Macro: retrying with reversed order...")
            all_moves = []
            placed_boxes = set()
            current_boxes = set(engine.boxes)
            player_r, player_c = engine.player_r, engine.player_c
            total_states = 0
        
        success = True
        for step, ((box_r, box_c), (tgt_r, tgt_c)) in enumerate(ordering):
            elapsed = time.time() - t_start
            if on_progress:
                pct = int(100 * (step + attempt * len(ordering)) / (len(ordering) * 2))
                on_progress(total_states, max_states_per_box * len(ordering),
                           elapsed)
            
            log(f"  Macro step {step+1}/{len(ordering)}: "
                f"push ({box_r},{box_c})→({tgt_r},{tgt_c}), "
                f"player at ({player_r},{player_c})")
            
            # Find current position of this box (it might have been pushed by
            # earlier steps if boxes share paths — but in macro mode we treat
            # unplaced boxes as obstacles, so they shouldn't move)
            # The box should still be at its original position
            if (box_r, box_c) not in current_boxes:
                log(f"    WARNING: box not at expected position, searching...")
                # Box might have been displaced — find closest unplaced box
                found = False
                for br, bc in current_boxes:
                    if (br, bc) not in placed_boxes:
                        box_r, box_c = br, bc
                        found = True
                        break
                if not found:
                    log(f"    FAILED: no movable box found")
                    success = False
                    break
            
            # Obstacles: all boxes EXCEPT the one we're moving
            obstacles = frozenset(
                (current_boxes - {(box_r, box_c)}) | placed_boxes
            )
            
            # Solve this single box
            moves = _solve_single_box_astar(
                engine, player_r, player_c, 
                box_r, box_c, tgt_r, tgt_c,
                obstacles, max_states=max_states_per_box)
            
            if moves is None:
                log(f"    FAILED: could not push box to target")
                success = False
                break
            
            log(f"    OK: {len(moves)} moves")
            all_moves.extend(moves)
            
            # Update state: replay moves to find new player + box positions
            sim_pr, sim_pc = player_r, player_c
            sim_br, sim_bc = box_r, box_c
            for d in moves:
                nbs = hex_neighbors(sim_pr, sim_pc)
                nr, nc = nbs[d]
                if (nr, nc) == (sim_br, sim_bc):
                    nbs_b = hex_neighbors(sim_br, sim_bc)
                    sim_br, sim_bc = nbs_b[d]
                sim_pr, sim_pc = nr, nc
            
            player_r, player_c = sim_pr, sim_pc
            current_boxes.discard((box_r, box_c))
            current_boxes.add((sim_br, sim_bc))
            placed_boxes.add((tgt_r, tgt_c))
            total_states += len(moves)
        
        if success:
            elapsed = time.time() - t_start
            log(f"  Macro-solver: SUCCESS! {len(all_moves)} moves in {elapsed:.2f}s")
            
            # Verify solution by full replay
            eng2 = HexobanEngine()
            eng2.load_from_lines(
                engine.to_xsb() if hasattr(engine, '_original_lines') 
                else _engine_to_lines(engine))
            # Actually replay on a fresh engine from the original state
            eng2 = HexobanEngine()
            eng2.grid = [row[:] for row in engine.grid]
            eng2.rows = engine.rows
            eng2.cols = engine.cols
            eng2.player_r = engine.player_r
            eng2.player_c = engine.player_c
            eng2.boxes = set(engine.boxes)
            eng2.targets = set(engine.targets)
            eng2.moves = 0
            eng2.pushes = 0
            eng2.history = []
            eng2.future = []
            eng2._initial_state = None
            
            valid = True
            for d in all_moves:
                if not eng2.move(d):
                    log(f"  Macro: verification FAILED at move {eng2.moves}: {d}")
                    valid = False
                    break
            
            if valid and eng2.is_solved():
                log(f"  Macro: verified! {eng2.moves}m {eng2.pushes}p")
                if on_progress:
                    on_progress(total_states, total_states, elapsed)
                return all_moves
            elif valid:
                log(f"  Macro: moves valid but not solved — boxes: {eng2.boxes} targets: {eng2.targets}")
            else:
                log(f"  Macro: invalid moves in sequence")
            # Try next ordering
            continue
    
    elapsed = time.time() - t_start
    log(f"  Macro-solver: FAILED after {elapsed:.2f}s")
    return None


def _engine_to_lines(engine):
    """Helper to get XSB lines from engine state."""
    from src.levels import grid_to_xsb
    return grid_to_xsb(engine.grid, engine.player_r, engine.player_c, engine.boxes)


# ═══════════════════════════════════════════════════════════════════
# A* solver (full state-space)
# ═══════════════════════════════════════════════════════════════════

def _solve_astar(engine: HexobanEngine, max_states: int = 5_000_000,
                 on_progress: Optional[Callable] = None) -> Optional[list[str]]:
    """A* solver with push-distance heuristic."""
    targets_fs = frozenset(engine.targets)
    initial_boxes = frozenset(engine.boxes)
    initial_state = (engine.player_r, engine.player_c, initial_boxes)
    
    n_floor = sum(1 for r in range(engine.rows) for c in range(engine.cols)
                  if engine.grid[r][c] not in (WALL, EMPTY))
    use_push_dist = n_floor < 300
    if use_push_dist:
        push_dists = _compute_push_distances(engine)
        h0 = _heuristic_push(initial_boxes, push_dists, targets_fs)
        log(f"  A*: push-distance heuristic (h0={h0})")
    else:
        push_dists = None
        h0 = _heuristic_simple(initial_boxes, targets_fs)
        log(f"  A*: hex-distance heuristic (h0={h0})")
    
    counter = 0
    open_set = [(h0, counter, initial_state, [])]
    g_scores = {initial_state: 0}
    states_explored = 0
    t_start = time.time()
    last_report = t_start

    while open_set and states_explored < max_states:
        f, _, (pr, pc, boxes), path = heapq.heappop(open_set)
        states_explored += 1
        g = len(path)
        if g > g_scores.get((pr, pc, boxes), float('inf')):
            continue

        now = time.time()
        if on_progress and now - last_report > 0.5:
            on_progress(states_explored, max_states, now - t_start)
            last_report = now

        for dname in ALL_DIRS:
            nb = hex_neighbors(pr, pc)
            nr, nc = nb[dname]
            if not (0 <= nr < engine.rows and 0 <= nc < engine.cols):
                continue
            if engine.grid[nr][nc] in (WALL, EMPTY):
                continue
            new_boxes = boxes
            if (nr, nc) in boxes:
                bnb = hex_neighbors(nr, nc)
                br, bc = bnb[dname]
                if not (0 <= br < engine.rows and 0 <= bc < engine.cols):
                    continue
                if engine.grid[br][bc] in (WALL, EMPTY) or (br, bc) in boxes:
                    continue
                new_boxes = frozenset((boxes - {(nr, nc)}) | {(br, bc)})
                if _is_hex_deadlock(engine, br, bc):
                    continue

            new_state = (nr, nc, new_boxes)
            new_g = g + 1
            if new_g >= g_scores.get(new_state, float('inf')):
                continue
            g_scores[new_state] = new_g
            new_path = path + [dname]
            if new_boxes == targets_fs:
                elapsed = time.time() - t_start
                log(f"  A* solved: {len(new_path)}m, {states_explored:,} states, {elapsed:.2f}s")
                if on_progress:
                    on_progress(states_explored, max_states, elapsed)
                return new_path
            if push_dists:
                h = _heuristic_push(new_boxes, push_dists, targets_fs)
            else:
                h = _heuristic_simple(new_boxes, targets_fs)
            counter += 1
            heapq.heappush(open_set, (new_g + h, counter, new_state, new_path))

    elapsed = time.time() - t_start
    log(f"  A* exhausted: {states_explored:,} states in {elapsed:.2f}s")
    if on_progress:
        on_progress(states_explored, max_states, elapsed)
    return None


# ═══════════════════════════════════════════════════════════════════
# BFS solver (optimal for small puzzles)
# ═══════════════════════════════════════════════════════════════════

def _solve_bfs(engine: HexobanEngine, max_states: int = 1_000_000,
               on_progress: Optional[Callable] = None) -> Optional[list[str]]:
    initial = (engine.player_r, engine.player_c, frozenset(engine.boxes))
    visited = {initial}
    queue = deque([(initial, [])])
    states_explored = 0
    t_start = time.time()
    last_report = t_start

    while queue and states_explored < max_states:
        (pr, pc, boxes), path = queue.popleft()
        states_explored += 1
        now = time.time()
        if on_progress and now - last_report > 0.5:
            on_progress(states_explored, max_states, now - t_start)
            last_report = now

        for dname in ALL_DIRS:
            nb = hex_neighbors(pr, pc)
            nr, nc = nb[dname]
            if not (0 <= nr < engine.rows and 0 <= nc < engine.cols):
                continue
            if engine.grid[nr][nc] in (WALL, EMPTY):
                continue
            new_boxes = boxes
            if (nr, nc) in boxes:
                bnb = hex_neighbors(nr, nc)
                br, bc = bnb[dname]
                if not (0 <= br < engine.rows and 0 <= bc < engine.cols):
                    continue
                if engine.grid[br][bc] in (WALL, EMPTY) or (br, bc) in boxes:
                    continue
                new_boxes = frozenset((boxes - {(nr, nc)}) | {(br, bc)})
                if _is_hex_deadlock(engine, br, bc):
                    continue
            state = (nr, nc, new_boxes)
            if state in visited:
                continue
            visited.add(state)
            new_path = path + [dname]
            if new_boxes == engine.targets:
                elapsed = time.time() - t_start
                log(f"  BFS solved: {len(new_path)}m, {states_explored:,} states, {elapsed:.2f}s")
                return new_path
            queue.append((state, new_path))

    elapsed = time.time() - t_start
    log(f"  BFS exhausted: {states_explored:,} states in {elapsed:.2f}s")
    return None


# ═══════════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════════

def count_pushes(engine_data: list[str], moves: list[str]) -> int:
    eng = HexobanEngine()
    eng.load_from_lines(engine_data)
    pushes = 0
    for d in moves:
        old_boxes = frozenset(eng.boxes)
        eng.move(d)
        if frozenset(eng.boxes) != old_boxes:
            pushes += 1
    return pushes


# ═══════════════════════════════════════════════════════════════════
# Engine-driven BFS for extended levels (lasers / slabs / keys / gates)
# ═══════════════════════════════════════════════════════════════════

def _solve_bfs_extended(engine: HexobanEngine,
                        max_states: int = 500_000,
                        on_progress: Optional[Callable] = None) -> Optional[list[str]]:
    """BFS that uses engine.move() as the simulation primitive.

    Extended levels with lasers/slabs/keys/gates require the full engine
    semantics; re-implementing them in a tight hand-rolled loop would
    duplicate code and risk subtle divergence from in-game behaviour.

    State key (used for visited-set + dedup):
      (player_r, player_c,
       frozenset(boxes),
       tuple(held_keys),
       frozenset(opened_gates),
       frozenset(collected_keys))

    Per-node storage: a GameState snapshot (cheap — just immutable
    primitives and small frozensets) plus the accumulated path.

    Known weakness: carrying the path as `list[str]` per queue entry
    is O(depth) memory per entry. For the first correctness-first
    release this is tolerable; the review doc recommends switching to
    parent-pointer reconstruction once this is stable.
    """
    import time as _t

    def _make_key(state):
        # Include box_colors and switch_on so the solver distinguishes
        # states where the switch has been toggled or boxes of different
        # colors occupy the same positions. Include has_cbrn and
        # collapsed_tiles so the solver correctly tracks CBRN pickup
        # and crumble-tile consumption.
        return (state.player_r, state.player_c, state.boxes,
                state.held_keys, state.opened_gates, state.collected_keys,
                state.box_colors, state.switch_on,
                state.has_cbrn, state.collapsed_tiles, state.collected_cbrn)

    initial_state = engine._snapshot()
    initial_key = _make_key(initial_state)
    visited = {initial_key}
    queue = deque([(initial_state, [])])
    states_explored = 0
    t_start = _t.time()
    last_report = t_start

    # Check initial — a puzzle starting already-solved is a 0-move solution.
    if engine.is_solved():
        return []

    try:
        while queue and states_explored < max_states:
            state, path = queue.popleft()
            states_explored += 1

            now = _t.time()
            if on_progress and now - last_report > 0.5:
                on_progress(states_explored, max_states, now - t_start)
                last_report = now

            # Restore engine to this state before trying moves
            engine._restore(state)

            for dname in ALL_DIRS:
                # Snapshot-restore pattern: snapshot before, restore after.
                # We cannot rely on engine.undo() here because it clobbers
                # the redo stack in a way that breaks nested exploration.
                before = engine._snapshot()
                if not engine.move(dname):
                    # engine.move only snapshots on success, so no undo needed
                    continue
                new_state = engine._snapshot()
                new_key = _make_key(new_state)
                if new_key in visited:
                    engine._restore(before)
                    engine.history.clear()
                    engine.future.clear()
                    continue
                visited.add(new_key)
                new_path = path + [dname]
                # Goal check — use engine.is_solved() so colored-box/target
                # compatibility is enforced correctly. A position match is
                # necessary but not sufficient when colors are in play.
                if engine.is_solved():
                    elapsed = _t.time() - t_start
                    log(f"  BFS(ext) solved: {len(new_path)}m, "
                        f"{states_explored:,} states, {elapsed:.2f}s")
                    return new_path
                queue.append((new_state, new_path))
                # Restore engine to `state` for the next direction
                engine._restore(before)
                engine.history.clear()
                engine.future.clear()

        elapsed = _t.time() - t_start
        log(f"  BFS(ext) exhausted: {states_explored:,} states in {elapsed:.2f}s")
        return None
    finally:
        # Always leave the engine in its initial state regardless of outcome
        engine._restore(initial_state)
        engine.history.clear()
        engine.future.clear()


# ═══════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════

def _default_terminal_progress(label: str) -> Callable:
    """Return a progress callback that draws a refreshing stderr line.

    Used when solve() is invoked without an on_progress callback from a
    terminal-friendly context (CLI benchmark, script, etc). Only emits
    output if stderr is a TTY, so piping/redirecting doesn't get garbled
    by carriage returns.
    """
    import sys
    from src.solutions import log_progress
    if not sys.stderr.isatty():
        return None

    def _cb(states: int, budget: int, elapsed: float):
        log_progress(label, states, budget, elapsed)
    return _cb


def solve(engine: HexobanEngine,
          on_progress: Optional[Callable] = None) -> Optional[list[str]]:
    """Solve the current hex level. Tries multiple strategies in order.

    If `on_progress` is None and we detect a TTY on stderr, install a
    default progress monitor that draws a live-updating status line
    (states explored, rate, elapsed time). GUI callers pass their own
    callback and are unaffected.
    """
    n_boxes = len(engine.boxes)
    n_floor = sum(1 for r in range(engine.rows) for c in range(engine.cols)
                  if engine.grid[r][c] not in (WALL, EMPTY))
    log(f"Solving: {n_boxes} boxes, {n_floor} floor cells, grid {engine.rows}x{engine.cols}")

    # Install a default terminal progress monitor if none was provided
    # and we're attached to a terminal. The label updates per strategy.
    _caller_supplied_progress = on_progress is not None
    if on_progress is None:
        on_progress = _default_terminal_progress("solve")

    def _end_progress():
        if not _caller_supplied_progress:
            from src.solutions import log_progress_end
            log_progress_end()

    # Extended levels (lasers / slabs / keys / gates / portals / colored)
    # must use the engine-driven BFS.
    if _level_has_extended_tiles(engine):
        log(f"  Level uses extended tiles — dispatching to engine-driven BFS")
        try:
            return _solve_bfs_extended(engine, max_states=500_000, on_progress=on_progress)
        finally:
            _end_progress()

    try:
        # 1. BFS for trivial puzzles
        if n_boxes <= 1 or n_floor <= 30:
            result = _solve_bfs(engine, max_states=1_000_000, on_progress=on_progress)
            if result:
                return result

        # 2. A* for medium puzzles (try with modest budget first)
        if n_boxes <= 3 or n_floor <= 80:
            result = _solve_astar(engine, max_states=3_000_000, on_progress=on_progress)
            if result:
                return result

        # 3. Macro-solver for large/complex puzzles
        if n_boxes >= 2:
            log(f"  Trying macro-solver (per-box strategy)...")
            result = _solve_macro(engine, max_states_per_box=1_000_000,
                                  on_progress=on_progress)
            if result:
                return result

        # 4. Full A* as last resort with max budget
        if n_boxes > 1:
            log(f"  Last resort: full A* with 5M budget...")
            result = _solve_astar(engine, max_states=5_000_000, on_progress=on_progress)
            if result:
                return result

        return None
    finally:
        _end_progress()
