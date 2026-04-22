"""Core Hexoban game logic — pure data, no rendering.

Uses offset coordinates (odd-r) for the hex grid.
6 movement directions: TOP_LEFT, TOP_RIGHT, LEFT, RIGHT, BOTTOM_LEFT, BOTTOM_RIGHT.

Mechanics handled here:
  - Basic Sokoban push / undo / redo / restart
  - Slabs (pressure plates) disarming linked lasers
  - Colored keys collected by the player and consumed by matching gates
  - Portals (unidirectional): stepping on a blue portal teleports the
    player to the matching orange portal, but ONLY if the linked switch
    is ON. Switches latch (first touch turns on; next turn on turns off).
  - Colored boxes must be placed on colored targets of the same color to
    count toward the win condition. Uncolored (classic) boxes satisfy
    any uncolored target. Win requires every target covered by a valid
    match, and every box covering a valid match.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from src.levels import (
    WALL, FLOOR, TARGET, BOX, BOX_ON_TARGET, EMPTY,
    NUM_LASER_GROUPS, NUM_KEY_COLORS, NUM_BOX_COLORS,
    PORTAL_IN, PORTAL_OUT, SWITCH,
    CRUMBLE, RADIOACTIVE, CBRN_ITEM,
    parse_level, grid_to_xsb, hex_neighbors,
    is_slab, is_laser, is_key, is_gate,
    is_portal_in, is_portal_out, is_switch, is_colored_target,
    is_crumble, is_radioactive, is_cbrn_item,
    slab_group, laser_group, key_color, gate_color,
    target_color,
    is_walkable_base, is_blocking_base,
    is_colored_box_parse, is_colored_box_on_target_parse,
    colored_box_parse_color,
    colored_target_id,
)


@dataclass
class GameState:
    """Immutable snapshot for undo/redo.

    `box_colors` maps position -> color (-1 for uncolored). We store it
    as a tuple of (r, c, color) triples sorted by (r, c) so the state is
    hashable and order-stable.

    `switch_on` is a bool — the level has at most one switch, and it
    latches between off and on each time the player touches it.

    `has_cbrn` is a bool — True once the player has picked up the CBRN
    protective clothing item. Enables traversal of radioactive tiles.

    `collapsed_tiles` is a frozenset of (r, c) for crumble tiles that
    have collapsed into void after the player walked off them. Needed
    so undo / solver can roll back the grid mutation.

    `collected_cbrn` is a frozenset of (r, c) for CBRN items already
    picked up (so the item glyph isn't rendered or re-picked).
    """
    player_r: int
    player_c: int
    boxes: frozenset[tuple[int, int]]
    box_colors: tuple  # tuple of (r, c, color) triples sorted by (r, c)
    moves: int
    pushes: int
    held_keys: tuple
    opened_gates: frozenset[tuple[int, int]]
    collected_keys: frozenset[tuple[int, int]]
    switch_on: bool
    has_cbrn: bool
    collapsed_tiles: frozenset[tuple[int, int]]
    collected_cbrn: frozenset[tuple[int, int]]


@dataclass
class HexobanEngine:
    grid: list[list[int]] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    player_r: int = 0
    player_c: int = 0
    boxes: set[tuple[int, int]] = field(default_factory=set)
    targets: set[tuple[int, int]] = field(default_factory=set)
    # Colored targets: (r, c) -> color (0..NUM_BOX_COLORS-1). Regular TARGET
    # cells do not appear here.
    target_colors: dict = field(default_factory=dict)
    # Box colors: (r, c) -> color (0..NUM_BOX_COLORS-1). Uncolored boxes
    # ('$') do not appear here. Boxes not in this dict but in `self.boxes`
    # are uncolored.
    box_colors: dict = field(default_factory=dict)
    moves: int = 0
    pushes: int = 0
    history: list[GameState] = field(default_factory=list)
    future: list[GameState] = field(default_factory=list)
    max_undo: int = 500
    _initial_state: Optional[GameState] = field(default=None, repr=False)

    # Keys and gates
    held_keys: list[int] = field(default_factory=lambda: [0] * NUM_KEY_COLORS)
    opened_gates: set[tuple[int, int]] = field(default_factory=set)
    collected_keys: set[tuple[int, int]] = field(default_factory=set)

    # Portal and switch
    # switch_on: True if the (single) switch has been toggled on. Toggled
    # each time the player steps onto a switch tile.
    switch_on: bool = False
    # Portal destination cached at load time (None if no portal in level).
    _portal_out_rc: Optional[tuple] = field(default=None, repr=False)

    # CBRN / radioactive / crumble state
    # has_cbrn: True once the player has picked up the CBRN protective
    # clothing item. Required to walk on radioactive tiles.
    has_cbrn: bool = False
    # collapsed_tiles: positions of crumble tiles that have already
    # collapsed into void (after the player left them). The grid cell at
    # each of these positions is set to EMPTY for normal gameplay, but
    # we track the set explicitly so undo/snapshot can restore the
    # original CRUMBLE tile.
    collapsed_tiles: set[tuple[int, int]] = field(default_factory=set)
    # collected_cbrn: CBRN item tiles already picked up (typically one
    # per level, but we support multiple in case of future design).
    collected_cbrn: set[tuple[int, int]] = field(default_factory=set)

    # ---------- loading ----------

    def load_from_lines(self, lines: list[str]):
        """Parse hex XSB lines and initialise the engine."""
        self.grid, self.player_r, self.player_c = parse_level(lines)
        self.rows = len(self.grid)
        self.cols = len(self.grid[0]) if self.rows else 0
        self.boxes = set()
        self.targets = set()
        self.target_colors = {}
        self.box_colors = {}
        self._portal_out_rc = None
        for r, row in enumerate(self.grid):
            for c, tid in enumerate(row):
                # Classic box
                if tid == BOX:
                    self.boxes.add((r, c))
                    self.grid[r][c] = FLOOR
                elif tid == BOX_ON_TARGET:
                    self.boxes.add((r, c))
                    self.grid[r][c] = TARGET
                # Colored box sentinels left over from parse
                elif is_colored_box_parse(tid):
                    color = colored_box_parse_color(tid)
                    self.boxes.add((r, c))
                    self.box_colors[(r, c)] = color
                    self.grid[r][c] = FLOOR
                elif is_colored_box_on_target_parse(tid):
                    color = colored_box_parse_color(tid)
                    self.boxes.add((r, c))
                    self.box_colors[(r, c)] = color
                    # Underlying target is a colored target of matching color
                    self.grid[r][c] = colored_target_id(color)
                # After the above transforms, re-read tid for target bookkeeping
                final_tid = self.grid[r][c]
                if final_tid == TARGET:
                    self.targets.add((r, c))
                elif is_colored_target(final_tid):
                    self.targets.add((r, c))
                    self.target_colors[(r, c)] = target_color(final_tid)
                # Portal-out lookup (single destination)
                if is_portal_out(final_tid):
                    self._portal_out_rc = (r, c)
        self.moves = 0
        self.pushes = 0
        self.held_keys = [0] * NUM_KEY_COLORS
        self.opened_gates = set()
        self.collected_keys = set()
        self.switch_on = False
        self.has_cbrn = False
        self.collapsed_tiles = set()
        self.collected_cbrn = set()
        self.history.clear()
        self.future.clear()
        self._initial_state = self._snapshot()

    # ---------- state snapshots ----------

    def _snapshot(self) -> GameState:
        # box_colors stored as sorted tuple of (r, c, color) for hashability
        bc_tuple = tuple(sorted(
            (r, c, self.box_colors.get((r, c), -1)) for (r, c) in self.boxes
        ))
        return GameState(
            self.player_r, self.player_c,
            frozenset(self.boxes),
            bc_tuple,
            self.moves, self.pushes,
            tuple(self.held_keys),
            frozenset(self.opened_gates),
            frozenset(self.collected_keys),
            self.switch_on,
            self.has_cbrn,
            frozenset(self.collapsed_tiles),
            frozenset(self.collected_cbrn),
        )

    def _restore(self, s: GameState):
        self.player_r = s.player_r
        self.player_c = s.player_c
        self.boxes = set(s.boxes)
        self.box_colors = {(r, c): color for (r, c, color) in s.box_colors if color >= 0}
        self.moves = s.moves
        self.pushes = s.pushes
        self.held_keys = list(s.held_keys)
        self.opened_gates = set(s.opened_gates)
        self.collected_keys = set(s.collected_keys)
        self.switch_on = s.switch_on
        self.has_cbrn = s.has_cbrn
        # Restore grid cells that were previously collapsed to EMPTY but
        # should now be CRUMBLE again (undo scenario). Conversely, mark
        # cells that are collapsed in `s` as EMPTY in the grid.
        old_collapsed = set(self.collapsed_tiles)
        new_collapsed = set(s.collapsed_tiles)
        for (r, c) in old_collapsed - new_collapsed:
            self.grid[r][c] = CRUMBLE
        for (r, c) in new_collapsed - old_collapsed:
            self.grid[r][c] = EMPTY
        self.collapsed_tiles = new_collapsed
        self.collected_cbrn = set(s.collected_cbrn)

    # ---------- laser / gate / key helpers ----------

    def _slab_pressed(self, group: int, boxes: set, player_rc: tuple) -> bool:
        """True if at least one slab of `group` is occupied by player or box.

        Scans grid for slab tiles of the given group and checks occupancy.
        This is O(R*C) — fine for typical hex grids. Callers that need
        this in a hot loop (solver) should cache slab positions by group.
        """
        for r in range(self.rows):
            for c in range(self.cols):
                if is_slab(self.grid[r][c]) and slab_group(self.grid[r][c]) == group:
                    if (r, c) == player_rc or (r, c) in boxes:
                        return True
        return False

    def laser_active(self, r: int, c: int,
                     boxes: Optional[set] = None,
                     player_rc: Optional[tuple] = None) -> bool:
        """Return True if the laser at (r, c) is currently ON (deadly)."""
        tid = self.grid[r][c]
        if not is_laser(tid):
            return False
        g = laser_group(tid)
        if boxes is None:
            boxes = self.boxes
        if player_rc is None:
            player_rc = (self.player_r, self.player_c)
        return not self._slab_pressed(g, boxes, player_rc)

    def _cell_passable_for_player(self, r: int, c: int,
                                   boxes: set, held: list[int],
                                   has_cbrn: Optional[bool] = None) -> bool:
        """True if player can step onto (r, c) given current boxes and keys.

        Laser state is computed w.r.t. the *incoming* boxes/player. Since
        the player is moving INTO (r,c), we evaluate slab occupancy with the
        player at its old position and boxes where they'll be *after* push
        (caller handles box displacement first).

        `has_cbrn` defaults to the engine's current state if None. A
        radioactive tile is walkable only if has_cbrn is True.
        """
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return False
        tid = self.grid[r][c]
        if is_blocking_base(tid):
            return False
        if (r, c) in boxes:
            return False  # pushed-box handling is caller's responsibility
        if is_gate(tid) and (r, c) not in self.opened_gates:
            if held[gate_color(tid)] <= 0:
                return False  # gate locked, no matching key
        if is_laser(tid):
            g = laser_group(tid)
            if not self._slab_pressed(g, boxes, (self.player_r, self.player_c)):
                return False  # laser ON → deadly
        if is_radioactive(tid):
            cbrn = self.has_cbrn if has_cbrn is None else has_cbrn
            if not cbrn:
                return False  # radioactive deadly without protective suit
        return True

    def _cell_passable_for_box(self, r: int, c: int, boxes: set) -> bool:
        """True if a box can occupy (r, c).

        Boxes can rest on floor/target/slab. They cannot enter gates,
        key tiles (keys are player-only), walls, voids, or active lasers.
        They also cannot enter radioactive tiles (CBRN protects the
        player, not the box; a pushed box on a radioactive tile is also
        undesirable design-wise), CBRN-item tiles (would consume the
        item without being pickable), or crumble tiles (the collapse
        mechanic is driven by the player leaving, not the box).
        """
        if not (0 <= r < self.rows and 0 <= c < self.cols):
            return False
        tid = self.grid[r][c]
        if is_blocking_base(tid):
            return False
        if (r, c) in boxes:
            return False
        if is_gate(tid) and (r, c) not in self.opened_gates:
            return False
        if is_key(tid) and (r, c) not in self.collected_keys:
            return False  # box can't squash a key
        if is_laser(tid):
            # `boxes` passed by caller excludes the moving box, so slab
            # occupancy from the push-source box is correctly ignored.
            g = laser_group(tid)
            if not self._slab_pressed(g, boxes, (self.player_r, self.player_c)):
                return False
        if is_radioactive(tid):
            return False
        if is_cbrn_item(tid) and (r, c) not in self.collected_cbrn:
            return False
        if is_crumble(tid):
            return False
        # Floor / target / slab / disarmed laser / opened gate: OK
        return True

    # ---------- movement (6 hex directions) ----------

    DIRECTIONS = ["TOP_LEFT", "TOP_RIGHT", "LEFT", "RIGHT", "BOTTOM_LEFT", "BOTTOM_RIGHT"]

    def move(self, direction: str) -> bool:
        """Try to move player in *direction*. Return True if moved.

        Side effects (all undoable):
          - Pushes a box if the adjacent cell holds one.
          - Collects a key if the destination is an uncollected key tile.
          - Opens a gate (consuming one matching-color key) if the
            destination is a locked gate tile.
          - Toggles the switch if the destination is a switch tile.
          - Teleports the player from portal-in to portal-out if the
            destination is portal-in AND the switch is currently ON.
            The teleport is mandatory — if the switch is ON but the
            destination is blocked, the step into portal-in is disallowed.
        """
        neighbors = hex_neighbors(self.player_r, self.player_c)
        if direction not in neighbors:
            return False
        nr, nc = neighbors[direction]

        if not (0 <= nr < self.rows and 0 <= nc < self.cols):
            return False
        tid = self.grid[nr][nc]

        # Absolute blockers
        if is_blocking_base(tid):
            return False

        pushed = False
        pushed_to = None
        if (nr, nc) in self.boxes:
            # Try to push the box one step further
            box_neighbors = hex_neighbors(nr, nc)
            if direction not in box_neighbors:
                return False
            br, bc = box_neighbors[direction]
            other_boxes = self.boxes - {(nr, nc)}
            if not self._cell_passable_for_box(br, bc, other_boxes):
                return False
            # Also: pushing a box INTO a portal-in does nothing special —
            # the box just rests on the portal tile. Portals only teleport
            # the player. This matches classic puzzle-game design: crates
            # block portals, they don't travel through them.
            pushed = True
            pushed_to = (br, bc)

        future_boxes = self.boxes
        if pushed:
            future_boxes = (self.boxes - {(nr, nc)}) | {pushed_to}

        # Gate check
        if is_gate(tid) and (nr, nc) not in self.opened_gates:
            if self.held_keys[gate_color(tid)] <= 0:
                return False
        # Laser check
        if is_laser(tid):
            g = laser_group(tid)
            if not self._slab_pressed_for(g, future_boxes, None):
                return False
        # Radioactive check — deadly unless the player has CBRN clothing.
        if is_radioactive(tid) and not self.has_cbrn:
            return False

        # Portal teleport pre-check: if the player is stepping onto a
        # portal-in and the switch is ON, the teleport MUST succeed; if
        # the destination is occupied by a box, the whole move is denied.
        teleport_to: Optional[tuple] = None
        if is_portal_in(tid) and self.switch_on and self._portal_out_rc is not None:
            pr_out, pc_out = self._portal_out_rc
            if (pr_out, pc_out) in future_boxes:
                return False  # destination blocked by a box
            # Portal-out is guaranteed walkable by grid construction
            # (is_walkable_base(PORTAL_OUT) is True). No further checks needed.
            teleport_to = (pr_out, pc_out)

        # Remember the player's CURRENT cell so we can collapse it later
        # if it was a crumble tile. The collapse has to happen AFTER the
        # player has moved (so the tile is vacated) but before the move
        # returns — snapshot for undo is already taken above.
        leaving_rc = (self.player_r, self.player_c)
        leaving_was_crumble = (is_crumble(self.grid[leaving_rc[0]][leaving_rc[1]]))

        # Commit — snapshot BEFORE any mutation so undo reverses everything
        self._push_undo()
        if pushed:
            self.boxes.discard((nr, nc))
            self.boxes.add(pushed_to)
            # Preserve color on the moved box
            if (nr, nc) in self.box_colors:
                self.box_colors[pushed_to] = self.box_colors.pop((nr, nc))
            self.pushes += 1
        self.player_r, self.player_c = nr, nc
        self.moves += 1

        # Pick up key if present
        if is_key(tid) and (nr, nc) not in self.collected_keys:
            self.held_keys[key_color(tid)] += 1
            self.collected_keys.add((nr, nc))
        # Open gate if present
        if is_gate(tid) and (nr, nc) not in self.opened_gates:
            self.held_keys[gate_color(tid)] -= 1
            self.opened_gates.add((nr, nc))
        # Toggle switch if present
        if is_switch(tid):
            self.switch_on = not self.switch_on
        # Pick up CBRN protective clothing if present
        if is_cbrn_item(tid) and (nr, nc) not in self.collected_cbrn:
            self.has_cbrn = True
            self.collected_cbrn.add((nr, nc))
        # Teleport if scheduled — happens after switch-toggle logic, so the
        # player teleports with the switch state as it WAS when entering
        # the portal. In practice players never step onto a switch that is
        # ALSO a portal-in (they are different tile types), so order is moot.
        if teleport_to is not None:
            self.player_r, self.player_c = teleport_to

        # Crumble collapse: if the player has just left a crumble tile,
        # turn it into void so it cannot be revisited. We do this AFTER
        # the teleport so that a player teleporting away from a crumble
        # tile also triggers the collapse. Collapsed tiles are tracked in
        # `self.collapsed_tiles` for undo/snapshot fidelity.
        if leaving_was_crumble and leaving_rc != (self.player_r, self.player_c):
            lr, lc = leaving_rc
            if self.grid[lr][lc] == CRUMBLE:
                self.grid[lr][lc] = EMPTY
                self.collapsed_tiles.add(leaving_rc)

        self.future.clear()
        return True

    def _slab_pressed_for(self, group: int, boxes: set,
                          player_rc: Optional[tuple]) -> bool:
        """Like _slab_pressed but accepts None player_rc (player absent).

        When evaluating whether a laser is safe for the player to step onto,
        we want boxes (post-push) to count, and optionally ignore the player
        (since they're mid-move). Used when computing the destination laser
        state AFTER the player moves there.
        """
        for r in range(self.rows):
            for c in range(self.cols):
                t = self.grid[r][c]
                if is_slab(t) and slab_group(t) == group:
                    if (r, c) in boxes:
                        return True
                    if player_rc is not None and (r, c) == player_rc:
                        return True
        return False

    # ---------- undo / redo ----------

    def _push_undo(self):
        self.history.append(self._snapshot())
        if len(self.history) > self.max_undo:
            self.history.pop(0)

    def undo(self) -> bool:
        if not self.history:
            return False
        self.future.append(self._snapshot())
        self._restore(self.history.pop())
        return True

    def redo(self) -> bool:
        if not self.future:
            return False
        self.history.append(self._snapshot())
        self._restore(self.future.pop())
        return True

    def restart(self):
        if self._initial_state:
            self.history.clear()
            self.future.clear()
            self._restore(self._initial_state)

    # ---------- win ----------

    def is_solved(self) -> bool:
        """True if every box sits on a compatible target and vice versa.

        Compatibility rules:
          - An uncolored (classic) box matches an uncolored target only.
          - A colored box matches a colored target of the same color only.

        This generalizes classic Sokoban: with no colored tiles at all,
        the check reduces to `self.boxes == self.targets`, which is the
        previous v1 behavior.
        """
        if not self.targets:
            return False
        # Positions must match
        if self.boxes != self.targets:
            return False
        # For each box/target position, verify color compatibility
        for pos in self.boxes:
            box_c = self.box_colors.get(pos, -1)        # -1 = uncolored
            tgt_c = self.target_colors.get(pos, -1)     # -1 = uncolored
            if box_c != tgt_c:
                return False
        return True

    # ---------- export ----------

    def to_xsb(self) -> list[str]:
        return grid_to_xsb(self.grid, self.player_r, self.player_c, self.boxes)

    # ---------- deadlock detection (hex-adapted) ----------

    def is_simple_deadlock(self, r: int, c: int) -> bool:
        """Check if a box at (r,c) is in a trivial corner deadlock on hex grid."""
        if (r, c) in self.targets:
            return False

        neighbors = hex_neighbors(r, c)
        adjacent_pairs = [
            ("TOP_LEFT", "LEFT"),
            ("LEFT", "BOTTOM_LEFT"),
            ("BOTTOM_LEFT", "BOTTOM_RIGHT"),
            ("BOTTOM_RIGHT", "RIGHT"),
            ("RIGHT", "TOP_RIGHT"),
            ("TOP_RIGHT", "TOP_LEFT"),
        ]
        for d1, d2 in adjacent_pairs:
            nr1, nc1 = neighbors[d1]
            nr2, nc2 = neighbors[d2]
            blocked1 = (not (0 <= nr1 < self.rows and 0 <= nc1 < self.cols)
                        or self.grid[nr1][nc1] in (WALL, EMPTY))
            blocked2 = (not (0 <= nr2 < self.rows and 0 <= nc2 < self.cols)
                        or self.grid[nr2][nc2] in (WALL, EMPTY))
            if blocked1 and blocked2:
                return True
        return False


# Backward compat alias
SokobanEngine = HexobanEngine
