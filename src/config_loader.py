"""Configuration loader for Hexoban — reads config.json."""
import json
import ctypes
import platform
from pathlib import Path


def _detect_screen_size():
    """Return (width, height) of the primary monitor."""
    system = platform.system()
    try:
        if system == "Linux":
            import subprocess
            out = subprocess.check_output(
                ["xrandr", "--current"], text=True, timeout=3
            )
            for line in out.splitlines():
                if "*" in line:
                    res = line.split()[0]
                    w, h = res.split("x")
                    return int(w), int(h)
        elif system == "Windows":
            user32 = ctypes.windll.user32
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        elif system == "Darwin":
            import subprocess
            out = subprocess.check_output(
                ["system_profiler", "SPDisplaysDataType"], text=True, timeout=5
            )
            for line in out.splitlines():
                if "Resolution" in line:
                    parts = line.split()
                    return int(parts[1]), int(parts[3])
    except Exception:
        pass
    return 1024, 768


def load_config(path: str = "config.json") -> dict:
    """Return a flat dict with typed settings from JSON config."""
    cfg_path = Path(path)
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = json.load(f)

    display = cfg.get("display", {})
    keys_cfg = cfg.get("keys", {})
    game = cfg.get("game", {})

    autodetect = display.get("autodetect", True)
    if autodetect:
        sw, sh = _detect_screen_size()
        win_w = int(sw * 0.85)
        win_h = int(sh * 0.85)
    else:
        win_w = display.get("default_width", 1024)
        win_h = display.get("default_height", 768)

    tile_size = display.get("tile_size", 64)
    fullscreen = display.get("fullscreen", False)

    return {
        "win_width": win_w,
        "win_height": win_h,
        "tile_size": tile_size,
        "fullscreen": fullscreen,
        # Hex directions (6 directions)
        "key_top_left": keys_cfg.get("move_top_left", "KP_7"),
        "key_top_right": keys_cfg.get("move_top_right", "KP_9"),
        "key_left": keys_cfg.get("move_left", "KP_4"),
        "key_right": keys_cfg.get("move_right", "KP_6"),
        "key_bottom_left": keys_cfg.get("move_bottom_left", "KP_1"),
        "key_bottom_right": keys_cfg.get("move_bottom_right", "KP_3"),
        # Other keys
        "key_undo": keys_cfg.get("undo", "z"),
        "key_redo": keys_cfg.get("redo", "y"),
        "key_restart": keys_cfg.get("restart", "r"),
        "key_fullscreen": keys_cfg.get("fullscreen_toggle", "f"),
        "key_quit": keys_cfg.get("quit", "ESCAPE"),
        "key_help": keys_cfg.get("help", "h"),
        "key_menu": keys_cfg.get("menu", "m"),
        "max_undo": game.get("max_undo", 500),
        "animation_speed": game.get("animation_speed", 8.0),
    }
