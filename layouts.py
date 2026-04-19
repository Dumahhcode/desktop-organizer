"""
Load, save, and apply named layout modes for Desktop Organizer.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import window_manager

_LAYOUT_PATH = Path(__file__).resolve().parent / "layouts.json"


def _default_data() -> dict:
    """Return an empty layouts document structure."""
    return {"modes": []}


def load_layouts() -> dict:
    """
    Load layouts from layouts.json, creating a default file if missing or invalid.
    """
    if not _LAYOUT_PATH.exists():
        data = _default_data()
        save_layouts(data)
        return data
    try:
        text = _LAYOUT_PATH.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or "modes" not in data:
            raise ValueError("invalid root")
        if not isinstance(data["modes"], list):
            raise ValueError("invalid modes")
        return data
    except Exception as exc:
        print(f"[layouts] load_layouts failed ({exc}), resetting to defaults")
        data = _default_data()
        save_layouts(data)
        return data


def save_layouts(data: dict) -> None:
    """
    Persist the full layouts document to layouts.json.
    """
    try:
        _LAYOUT_PATH.write_text(
            json.dumps(data, indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        print(f"[layouts] save_layouts failed: {exc}")


def get_mode_names() -> List[str]:
    """Return the names of all configured modes in file order."""
    data = load_layouts()
    names: List[str] = []
    for mode in data.get("modes", []):
        name = mode.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def get_mode(mode_name: str) -> Optional[dict]:
    """Return a mode dict by name, or None if not found."""
    target = (mode_name or "").strip()
    for mode in load_layouts().get("modes", []):
        if isinstance(mode, dict) and mode.get("name") == target:
            return mode
    return None


def add_mode(name: str) -> bool:
    """
    Append a new empty mode. Returns False if the name already exists or is blank.
    """
    label = (name or "").strip()
    if not label:
        return False
    data = load_layouts()
    for mode in data.get("modes", []):
        if mode.get("name") == label:
            return False
    data.setdefault("modes", []).append({"name": label, "apps": []})
    save_layouts(data)
    return True


def delete_mode(mode_name: str) -> bool:
    """Remove a mode by name. Returns False if it did not exist."""
    target = (mode_name or "").strip()
    data = load_layouts()
    modes = data.get("modes", [])
    new_modes = [m for m in modes if m.get("name") != target]
    if len(new_modes) == len(modes):
        return False
    data["modes"] = new_modes
    save_layouts(data)
    return True


def add_app_to_mode(mode_name: str, app_config: dict) -> bool:
    """
    Append an app configuration dict to the named mode.

    Returns False if the mode does not exist.
    """
    label = (mode_name or "").strip()
    if not get_mode(label):
        return False
    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == label:
            apps = m.setdefault("apps", [])
            apps.append(dict(app_config))
            break
    else:
        return False
    save_layouts(data)
    return True


def remove_app_from_mode(mode_name: str, app_index: int) -> bool:
    """
    Remove an app entry by index from a mode. Returns False on invalid index or mode.
    """
    label = (mode_name or "").strip()
    if not get_mode(label):
        return False
    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == label:
            apps = m.get("apps", [])
            if app_index < 0 or app_index >= len(apps):
                return False
            apps.pop(app_index)
            save_layouts(data)
            return True
    return False


def update_app_in_mode(mode_name: str, app_index: int, app_config: dict) -> bool:
    """
    Replace an app entry at app_index with app_config. Returns False if invalid.
    """
    label = (mode_name or "").strip()
    if not get_mode(label):
        return False
    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == label:
            apps = m.get("apps", [])
            if app_index < 0 or app_index >= len(apps):
                return False
            apps[app_index] = dict(app_config)
            save_layouts(data)
            return True
    return False


def _normalize_process_name(name: str) -> str:
    """Normalize user input to a lowercase ``*.exe`` basename for matching."""
    base = os.path.basename((name or "").strip())
    if not base.lower().endswith(".exe"):
        base = f"{base}.exe"
    return base.lower()


def _get_monitor_bounds(monitors: List[dict], monitor_index: int) -> Optional[tuple]:
    """Return ``(x, y, width, height)`` for a monitor index, or ``None``."""
    for mon in monitors:
        if int(mon["index"]) == int(monitor_index):
            return (int(mon["x"]), int(mon["y"]), int(mon["width"]), int(mon["height"]))
    return None


def rect_for_preset(
    monitor_bounds: tuple,
    preset: str,
    position: Optional[dict],
) -> tuple:
    """
    Compute (x, y, width, height) in screen coordinates for a preset on a monitor.

    Supported presets: left_half, right_half, top_half, bottom_half, maximized,
    custom. For custom, position must include x, y, width, height in screen space.
    """
    mx, my, mw, mh = monitor_bounds
    preset_key = (preset or "custom").strip().lower()
    if preset_key == "maximized":
        return (mx, my, mw, mh)
    if preset_key == "left_half":
        return (mx, my, mw // 2, mh)
    if preset_key == "right_half":
        w = mw - mw // 2
        return (mx + mw // 2, my, w, mh)
    if preset_key == "top_half":
        return (mx, my, mw, mh // 2)
    if preset_key == "bottom_half":
        h = mh - mh // 2
        return (mx, my + mh // 2, mw, h)
    pos = position or {}
    try:
        x = int(pos.get("x", mx))
        y = int(pos.get("y", my))
        w = int(pos.get("width", mw))
        h = int(pos.get("height", mh))
    except Exception:
        x, y, w, h = mx, my, mw, mh
    return (x, y, max(1, w), max(1, h))


def apply_mode(mode_name: str) -> None:
    """
    Apply a saved mode: launch missing apps, then move matching windows into place.

    Errors are printed to the console; this function does not raise for common failures.
    """
    mode = get_mode(mode_name)
    if not mode:
        print(f"[layouts] apply_mode: unknown mode {mode_name!r}")
        return
    monitors = window_manager.get_monitors()
    if not monitors:
        print("[layouts] apply_mode: no monitors detected")
        return
    apps = mode.get("apps") or []
    for app in apps:
        try:
            _apply_single_app(app, monitors)
        except Exception as exc:
            print(f"[layouts] apply_mode error for {app!r}: {exc}")


def _apply_single_app(app: dict, monitors: List[dict]) -> None:
    """Apply geometry and launch rules for one app entry."""
    process_name = _normalize_process_name(str(app.get("process_name", "")))
    if not process_name or process_name == ".exe":
        print("[layouts] skipping app with empty process_name")
        return
    title_match = app.get("window_title_match")
    title_match_str = str(title_match).strip() if title_match else None
    launch_path = app.get("launch_path")
    launch_path_str = str(launch_path).strip() if launch_path else ""
    try:
        monitor_index = int(app.get("monitor_index", 0))
    except Exception:
        monitor_index = 0
    preset = str(app.get("preset", "custom"))
    position = app.get("position") if isinstance(app.get("position"), dict) else {}

    bounds = _get_monitor_bounds(monitors, monitor_index)
    if not bounds:
        print(
            f"[layouts] monitor_index {monitor_index} out of range; using primary"
        )
        primary = next((m for m in monitors if m.get("is_primary")), monitors[0])
        bounds = (
            int(primary["x"]),
            int(primary["y"]),
            int(primary["width"]),
            int(primary["height"]),
        )
    x, y, w, h = rect_for_preset(bounds, preset, position)

    hwnd = window_manager.find_window_by_process(process_name, title_match_str)
    if hwnd is None and launch_path_str:
        print(f"[layouts] launching {launch_path_str!r} for {process_name}")
        window_manager.launch_app(launch_path_str)
        hwnd = window_manager.wait_for_window(process_name, title_match_str)
        if hwnd is None:
            print(f"[layouts] window for {process_name} did not appear in time")
            return
    if hwnd is None:
        print(f"[layouts] no window found for {process_name}")
        return
    window_manager.move_window(hwnd, x, y, w, h)


def capture_current_layout_to_mode(mode_name: str) -> int:
    """
    Replace the named mode's apps with a snapshot of currently open windows.

    Excludes this application's own organizer windows by title substring.
    Returns the number of captured apps.
    """
    label = (mode_name or "").strip()
    if not get_mode(label):
        print(f"[layouts] capture: unknown mode {mode_name!r}")
        return 0
    snapshots: List[dict] = []
    for win in window_manager.list_open_windows():
        title = win.get("title") or ""
        if "Desktop Organizer" in title:
            continue
        proc = win.get("process_name") or ""
        if not proc:
            continue
        x, y, w, h = win["rect"]
        snapshots.append(
            {
                "process_name": proc,
                "window_title_match": title[:120] if title else "",
                "launch_path": "",
                "monitor_index": int(win.get("monitor_index", 0)),
                "position": {"x": x, "y": y, "width": w, "height": h},
                "preset": "custom",
            }
        )
    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == label:
            m["apps"] = snapshots
            break
    save_layouts(data)
    return len(snapshots)
