"""
Load, save, and apply named layout modes for Desktop Organizer.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import window_manager


def _get_user_data_dir() -> Path:
    """
    Return the folder where user-editable data (layouts.json) lives.

    Uses %APPDATA%\\DesktopOrganizer on Windows so the file persists across
    application updates and PyInstaller bundle extractions.
    """
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "DesktopOrganizer"
    return Path.home() / ".desktop-organizer"


def _get_bundled_default_path() -> Path:
    """Return the path to the bundled default layouts.json (read-only)."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent
    return base / "layouts.json"


def _get_layout_path() -> Path:
    """Return the active layouts.json path, seeding from bundled default if needed."""
    user_dir = _get_user_data_dir()
    user_dir.mkdir(parents=True, exist_ok=True)
    user_path = user_dir / "layouts.json"
    if not user_path.exists():
        bundled = _get_bundled_default_path()
        if bundled.exists():
            try:
                user_path.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as exc:
                print(f"[layouts] seed from bundled default failed: {exc}")
                user_path.write_text(json.dumps(_default_data(), indent=4), encoding="utf-8")
        else:
            user_path.write_text(json.dumps(_default_data(), indent=4), encoding="utf-8")
    return user_path


def _default_data() -> dict:
    """Return an empty layouts document structure."""
    return {"modes": [], "quick_launch": []}


def load_layouts() -> dict:
    """Load layouts from layouts.json, creating a default file if missing or invalid."""
    path = _get_layout_path()
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict) or "modes" not in data:
            raise ValueError("invalid root")
        if not isinstance(data["modes"], list):
            raise ValueError("invalid modes")
        if "quick_launch" not in data or not isinstance(data.get("quick_launch"), list):
            data["quick_launch"] = []
        return data
    except Exception as exc:
        print(f"[layouts] load_layouts failed ({exc}), resetting to defaults")
        data = _default_data()
        save_layouts(data)
        return data


def save_layouts(data: dict) -> None:
    """Persist the full layouts document to layouts.json."""
    path = _get_layout_path()
    try:
        path.write_text(
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
    """Append a new empty mode. Returns False if the name already exists or is blank."""
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


def rename_mode(old_name: str, new_name: str) -> bool:
    """Rename a mode."""
    old = (old_name or "").strip()
    new = (new_name or "").strip()
    if not old or not new or old == new:
        return False
    if get_mode(new):
        return False
    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == old:
            m["name"] = new
            save_layouts(data)
            return True
    return False


def add_app_to_mode(mode_name: str, app_config: dict) -> bool:
    """Append an app configuration dict to the named mode."""
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
    """Remove an app entry by index from a mode."""
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
    """Replace an app entry at app_index with app_config."""
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


def get_quick_launch() -> List[dict]:
    """Return the quick launch entries list."""
    data = load_layouts()
    ql = data.get("quick_launch")
    return list(ql) if isinstance(ql, list) else []


def add_quick_launch(app_config: dict) -> bool:
    """Append a quick launch entry."""
    if not isinstance(app_config, dict):
        return False
    data = load_layouts()
    data.setdefault("quick_launch", []).append(dict(app_config))
    save_layouts(data)
    return True


def remove_quick_launch(index: int) -> bool:
    """Remove a quick launch entry by index."""
    data = load_layouts()
    entries = data.setdefault("quick_launch", [])
    if not isinstance(entries, list):
        data["quick_launch"] = []
        save_layouts(data)
        return False
    if index < 0 or index >= len(entries):
        return False
    entries.pop(index)
    save_layouts(data)
    return True


def update_quick_launch(index: int, app_config: dict) -> bool:
    """Replace a quick launch entry by index."""
    if not isinstance(app_config, dict):
        return False
    data = load_layouts()
    entries = data.setdefault("quick_launch", [])
    if not isinstance(entries, list):
        data["quick_launch"] = []
        save_layouts(data)
        return False
    if index < 0 or index >= len(entries):
        return False
    entries[index] = dict(app_config)
    save_layouts(data)
    return True


def launch_or_focus(index: int) -> dict:
    """
    Launch or focus a quick launch entry by index.

    Focus behavior:
    - if chrome_profile is set and process is chrome.exe, match by profile
    - otherwise match by process name/title
    """
    try:
        idx = int(index)
    except Exception:
        return {"ok": False, "error": "invalid index"}
    entries = get_quick_launch()
    if idx < 0 or idx >= len(entries):
        return {"ok": False, "error": "entry not found"}
    item = entries[idx] or {}
    process_name = _normalize_process_name(str(item.get("process_name", "")))
    title_match = str(item.get("window_title_match") or "").strip() or None
    launch_path = str(item.get("launch_path") or "").strip()
    chrome_profile = str(item.get("chrome_profile") or "").strip() or None
    if not process_name or process_name == ".exe":
        return {"ok": False, "error": "missing process_name"}
    hwnd: Optional[int] = None
    try:
        if process_name == "chrome.exe" and chrome_profile:
            hwnd = window_manager.find_chrome_window_by_profile(chrome_profile, title_match)
        else:
            hwnd = window_manager.find_window_by_process(process_name, title_match)
        if hwnd:
            window_manager.focus_window(int(hwnd))
            return {"ok": True, "action": "focused"}
        if not launch_path:
            return {"ok": False, "error": "app not running and launch_path missing"}
        if not window_manager.launch_app(launch_path):
            return {"ok": False, "error": "launch failed"}
        return {"ok": True, "action": "launched"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _normalize_process_name(name: str) -> str:
    """Normalize user input to a lowercase ``*.exe`` basename."""
    base = os.path.basename((name or "").strip())
    if not base.lower().endswith(".exe"):
        base = f"{base}.exe"
    return base.lower()


def _get_monitor_bounds(monitors: List[dict], monitor_index: int):
    """Return (x, y, width, height) for a monitor index, or None."""
    for mon in monitors:
        if int(mon["index"]) == int(monitor_index):
            return (int(mon["x"]), int(mon["y"]), int(mon["width"]), int(mon["height"]))
    return None


def rect_for_preset(monitor_bounds, preset: str, position: Optional[dict]):
    """Compute (x, y, width, height) in screen coords for a preset on a monitor."""
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
    Apply a saved mode: launch missing apps, move matching windows into place,
    and minimize any other visible windows.
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

    # Track which hwnds we position so we can minimize everything else after.
    positioned_hwnds: set = set()
    for app in apps:
        try:
            hwnd = _apply_single_app(app, monitors)
            if hwnd:
                positioned_hwnds.add(int(hwnd))
        except Exception as exc:
            print(f"[layouts] apply_mode error for {app!r}: {exc}")

    # Minimize all other visible top-level windows.
    try:
        _minimize_unlisted(positioned_hwnds)
    except Exception as exc:
        print(f"[layouts] minimize_unlisted failed: {exc}")


def _minimize_unlisted(positioned_hwnds: set) -> None:
    """Minimize every visible top-level window not in positioned_hwnds."""
    # Skip our own organizer window by title.
    own_title_substrings = ("desktop organizer", "desktop.organizer", "pywebview")
    for win in window_manager.list_open_windows():
        hwnd = int(win["hwnd"])
        if hwnd in positioned_hwnds:
            continue
        title = (win.get("title") or "").lower()
        if any(sub in title for sub in own_title_substrings):
            continue
        window_manager.minimize_window(hwnd)


def _apply_single_app(app: dict, monitors: List[dict]) -> Optional[int]:
    """
    Apply geometry and launch rules for one app entry.

    Returns the hwnd it positioned, or None if it couldn't.
    """
    process_name = _normalize_process_name(str(app.get("process_name", "")))
    if not process_name or process_name == ".exe":
        print("[layouts] skipping app with empty process_name")
        return None
    title_match = app.get("window_title_match")
    title_match_str = str(title_match).strip() if title_match else None
    launch_path = app.get("launch_path")
    launch_path_str = str(launch_path).strip() if launch_path else ""
    chrome_profile = str(app.get("chrome_profile") or "").strip() or None
    try:
        monitor_index = int(app.get("monitor_index", 0))
    except Exception:
        monitor_index = 0
    preset = str(app.get("preset", "custom"))
    position = app.get("position") if isinstance(app.get("position"), dict) else {}

    bounds = _get_monitor_bounds(monitors, monitor_index)
    if not bounds:
        print(f"[layouts] monitor_index {monitor_index} out of range; using primary")
        primary = next((m for m in monitors if m.get("is_primary")), monitors[0])
        bounds = (
            int(primary["x"]),
            int(primary["y"]),
            int(primary["width"]),
            int(primary["height"]),
        )
    x, y, w, h = rect_for_preset(bounds, preset, position)

    # Step 1: try to find an existing window
    hwnd: Optional[int] = None
    if process_name == "chrome.exe" and chrome_profile:
        hwnd = window_manager.find_chrome_window_by_profile(chrome_profile, title_match_str)
    else:
        hwnd = window_manager.find_window_by_process(process_name, title_match_str)

    # Step 2: if not running and we have a launch command, launch it
    if hwnd is None and launch_path_str:
        print(f"[layouts] launching {launch_path_str!r} for {process_name}")
        window_manager.launch_app(launch_path_str)
        if process_name == "chrome.exe" and chrome_profile:
            hwnd = window_manager.wait_for_chrome_profile_window(
                chrome_profile, title_match_str, timeout_sec=10.0
            )
        else:
            hwnd = window_manager.wait_for_window(
                process_name, title_match_str, timeout_sec=10.0
            )
        if hwnd is None:
            print(f"[layouts] window for {process_name} did not appear in time")
            return None

    if hwnd is None:
        print(f"[layouts] no window found for {process_name} (no launch_path set)")
        return None

    window_manager.move_window(hwnd, x, y, w, h)
    return hwnd


def capture_current_layout_to_mode(mode_name: str) -> int:
    """
    Replace the named mode's apps with a snapshot of currently open windows.

    Saves the exe path as launch_path and detects Chrome profiles so the mode
    can relaunch missing apps on apply.
    """
    label = (mode_name or "").strip()
    if not get_mode(label):
        print(f"[layouts] capture: unknown mode {mode_name!r}")
        return 0

    # Skip tabs/dialogs of our own app and off-screen ghost windows.
    snapshots: List[dict] = []
    for win in window_manager.list_open_windows():
        title = win.get("title") or ""
        tl = title.lower()
        if "desktop organizer" in tl or "desktop.organizer" in tl or "pywebview" in tl:
            continue
        proc = win.get("process_name") or ""
        if not proc:
            continue
        launch_hint = str(win.get("launch_hint") or "").strip()
        # UWP frame windows without a launch hint are not useful to capture.
        if proc.lower() == "applicationframehost.exe" and not launch_hint:
            continue
        x, y, w, h = win["rect"]
        entry: Dict[str, Any] = {
            "process_name": proc,
            "window_title_match": title[:120] if title else "",
            "launch_path": launch_hint,
            "monitor_index": int(win.get("monitor_index", 0)),
            "position": {"x": x, "y": y, "width": w, "height": h},
            "preset": "custom",
        }
        if win.get("chrome_profile"):
            entry["chrome_profile"] = win["chrome_profile"]
        snapshots.append(entry)

    data = load_layouts()
    for m in data.get("modes", []):
        if m.get("name") == label:
            m["apps"] = snapshots
            break
    save_layouts(data)
    return len(snapshots)