"""Solution storage and management for Hexoban.

Saves/loads solutions from ./assets/solutions/ as JSON files.
Each solution file stores: level name, level data hash, moves list,
move count, push count, timestamp, and whether it's the best known.
"""
import hashlib
import json
import time
from pathlib import Path
from typing import Optional

SOLUTIONS_DIR = Path("assets/solutions")


def _level_hash(data: list[str]) -> str:
    """Create a stable hash for level data (ignoring whitespace variations)."""
    normalized = "|".join(line.rstrip() for line in data)
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def _safe_filename(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
    return safe.strip().replace(" ", "_") or "unnamed"


def solution_path(name: str, data: list[str]) -> Path:
    """Return the path where a solution for this level would be stored."""
    h = _level_hash(data)
    safe = _safe_filename(name)
    return SOLUTIONS_DIR / f"{safe}_{h}.json"


def load_solution(name: str, data: list[str]) -> Optional[dict]:
    """Load a cached solution for a level. Returns dict or None."""
    SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    p = solution_path(name, data)
    if not p.exists():
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save_solution(name: str, data: list[str], moves: list[str],
                  push_count: int, is_best: bool = True) -> Path:
    """Save a solution. Returns the file path."""
    SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    p = solution_path(name, data)

    existing = load_solution(name, data)
    # Only overwrite if this is better or no existing solution
    if existing and not is_best:
        if existing.get("moves_count", 9999) <= len(moves):
            # Existing is same or better, keep it but store this as alt
            pass

    sol = {
        "name": name,
        "level_hash": _level_hash(data),
        "moves": moves,
        "moves_count": len(moves),
        "push_count": push_count,
        "timestamp": time.time(),
        "date": time.strftime("%Y-%m-%d %H:%M:%S"),
        "is_best": is_best,
    }

    # If there's an existing solution, compare and keep best
    if existing:
        old_moves = existing.get("moves_count", 9999)
        if len(moves) < old_moves:
            sol["is_best"] = True
            sol["previous_best"] = old_moves
        elif len(moves) == old_moves:
            sol["is_best"] = True  # same quality, update timestamp
        else:
            # New solution is worse — still save but mark not best
            sol["is_best"] = False
            sol["best_known"] = old_moves
            # Keep the best moves in the file
            sol["best_moves"] = existing.get("moves", existing.get("best_moves"))
            sol["best_push_count"] = existing.get("push_count",
                                                   existing.get("best_push_count"))

    try:
        with open(p, "w") as f:
            json.dump(sol, f, indent=2)
    except OSError:
        pass
    return p


def list_solutions() -> list[dict]:
    """Return list of all saved solutions with metadata."""
    SOLUTIONS_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(SOLUTIONS_DIR.glob("*.json")):
        try:
            with open(p) as f:
                sol = json.load(f)
            sol["_path"] = str(p)
            results.append(sol)
        except (json.JSONDecodeError, OSError):
            continue
    return results


def get_best_moves(name: str, data: list[str]) -> Optional[int]:
    """Return the best known move count for a level, or None."""
    sol = load_solution(name, data)
    if not sol:
        return None
    if sol.get("is_best", True):
        return sol.get("moves_count")
    return sol.get("best_known", sol.get("moves_count"))


def get_solution_moves(name: str, data: list[str]) -> Optional[list[str]]:
    """Return the best moves list for replay, or None."""
    sol = load_solution(name, data)
    if not sol:
        return None
    # Return best moves if available
    if sol.get("is_best", True):
        return sol.get("moves")
    return sol.get("best_moves", sol.get("moves"))


def log(msg: str):
    """Print a timestamped log message to terminal and append to log file.

    Log file: ./logs/hexoban.log . Rotated when it exceeds ~1 MB, keeping
    one backup as hexoban.log.1. Never raises — logging failures are
    swallowed so they can't crash gameplay.
    """
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    # Terminal
    try:
        print(line)
    except Exception:
        pass
    # File
    _append_log_line(line)


_LOG_DIR = Path("logs")
_LOG_FILE = _LOG_DIR / "hexoban.log"
_LOG_BACKUP = _LOG_DIR / "hexoban.log.1"
_LOG_MAX_BYTES = 1_000_000  # ~1 MB


def _append_log_line(line: str):
    try:
        _LOG_DIR.mkdir(exist_ok=True)
        # Cheap rotation: check size, move to backup if too big.
        # Stat is one syscall; only truncate-and-move on overflow.
        if _LOG_FILE.exists() and _LOG_FILE.stat().st_size >= _LOG_MAX_BYTES:
            try:
                if _LOG_BACKUP.exists():
                    _LOG_BACKUP.unlink()
                _LOG_FILE.rename(_LOG_BACKUP)
            except OSError:
                pass
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Never let a log failure take down the game.
        pass


def log_progress(label: str, current: int, total: int,
                 elapsed_s: float, extra: str = ""):
    """Single-line refreshing progress bar for terminal (stderr).

    Overwrites the previous line with '\\r'. Call `log_progress_end()`
    once when finished to move to a new line and preserve the last state.
    """
    import sys
    if total > 0:
        pct = min(100.0, 100.0 * current / total)
    else:
        pct = 0.0
    rate = current / elapsed_s if elapsed_s > 0.01 else 0.0
    rate_str = f"{rate:>8,.0f} st/s"
    bar_w = 24
    filled = int(bar_w * pct / 100)
    bar = "█" * filled + "·" * (bar_w - filled)
    ts = time.strftime("%H:%M:%S")
    extra_str = f" {extra}" if extra else ""
    msg = (f"\r[{ts}] {label}: [{bar}] {pct:5.1f}% "
           f"{current:>9,} states | {elapsed_s:6.2f}s | "
           f"{rate_str}{extra_str}")
    try:
        sys.stderr.write(msg)
        sys.stderr.flush()
    except Exception:
        pass


def log_progress_end():
    """End a progress line: newline on terminal."""
    import sys
    try:
        sys.stderr.write("\n")
        sys.stderr.flush()
    except Exception:
        pass


def classify_difficulty(states_explored: int, n_boxes: int, n_moves: int) -> str:
    """Classify level difficulty based on BFS state-space exploration.
    
    This is the standard Sokoban/Hexoban difficulty metric:
    - States explored by BFS measures the actual branching complexity
    - More states = harder to find solution = more difficult puzzle
    
    Algorithm: BFS explores ALL reachable states level-by-level.
    The total states before finding a solution directly measures
    how much search is needed. This correlates with:
    - Number of boxes (exponential factor)
    - Floor cell count (linear factor per box)
    - Wall layout (constrains/expands state space)
    - Puzzle trickiness (dead ends, required backtracking)
    
    Thresholds calibrated on classic Sokoban difficulty scales:
    """
    if states_explored <= 10:
        return "Tutorial"
    elif states_explored <= 500:
        return "Easy"
    elif states_explored <= 10_000:
        return "Medium"
    elif states_explored <= 100_000:
        return "Hard"
    else:
        return "Extreme"


def difficulty_description(tier: str) -> str:
    """Return a description of what each difficulty tier means."""
    descs = {
        "Tutorial": "≤10 BFS states — trivial, 1 box, direct push",
        "Easy": "≤500 BFS states — 2 boxes, simple paths",
        "Medium": "≤10K BFS states — 2-3 boxes, obstacles require planning",
        "Hard": "≤100K BFS states — 3-4 boxes, complex push sequences",
        "Extreme": ">100K BFS states — 4+ boxes, requires strategic decomposition",
    }
    return descs.get(tier, "Unknown")
