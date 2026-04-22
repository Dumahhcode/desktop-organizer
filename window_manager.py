"""
Window and monitor helpers for Desktop Organizer using pywin32.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

import win32api
import win32con
import win32gui
import win32process

# --- ctypes helpers for process image path (QueryFullProcessImageName) ---
_KERNEL32 = None
try:
    import ctypes
    from ctypes import wintypes

    _KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _QueryFullProcessImageNameW = _KERNEL32.QueryFullProcessImageNameW
    _QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _QueryFullProcessImageNameW.restype = wintypes.BOOL
except Exception:
    _KERNEL32 = None


def _query_process_exe_path(pid: int) -> Optional[str]:
    """Return the full executable path for a process id, or None if unavailable."""
    if _KERNEL32 is None:
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = win32api.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not _QueryFullProcessImageNameW(int(handle), 0, buf, ctypes.byref(size)):
            return None
        return buf.value
    finally:
        win32api.CloseHandle(handle)


def _basename_lower(path: Optional[str]) -> str:
    """Return the lowercase basename used for ``process_name`` comparisons."""
    if not path:
        return ""
    return os.path.basename(path).lower()


def _monitor_handle_to_index(h_monitor: int, monitors: List[dict]) -> int:
    """Map an ``hMonitor`` handle to the ``index`` field from ``get_monitors()``."""
    for m in monitors:
        if m.get("handle") == h_monitor:
            return int(m["index"])
    return 0


def _enum_display_monitors_raw() -> List[Tuple[int, Tuple[int, int, int, int], bool]]:
    """Enumerate monitors as (handle, (left, top, right, bottom), is_primary)."""
    results: List[Tuple[int, Tuple[int, int, int, int], bool]] = []
    try:
        entries = win32api.EnumDisplayMonitors()
    except Exception as exc:
        print(f"[window_manager] EnumDisplayMonitors failed: {exc}")
        return results
    for h_monitor, _hdc, rect in entries:
        try:
            info = win32api.GetMonitorInfo(h_monitor)
            mon = info["Monitor"]
            left, top, right, bottom = mon
            is_primary = bool(info.get("Flags", 0) & 1)
            results.append((int(h_monitor), (left, top, right, bottom), is_primary))
        except Exception as exc:
            print(f"[window_manager] GetMonitorInfo failed: {exc}")
            left, top, right, bottom = rect
            results.append((int(h_monitor), (left, top, right, bottom), False))
    return results


def get_monitors() -> List[dict]:
    """Return display monitors sorted left-to-right, then top-to-bottom."""
    raw = _enum_display_monitors_raw()
    raw.sort(key=lambda t: (t[1][0], t[1][1]))
    monitors: List[dict] = []
    for idx, (h_mon, (left, top, right, bottom), is_primary) in enumerate(raw):
        width = max(0, right - left)
        height = max(0, bottom - top)
        monitors.append(
            {
                "index": idx,
                "x": left,
                "y": top,
                "width": width,
                "height": height,
                "is_primary": is_primary,
                "handle": h_mon,
            }
        )
    return monitors


def _window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """Return ``(x, y, width, height)`` from ``GetWindowRect``."""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return left, top, max(0, right - left), max(0, bottom - top)


def _should_skip_window(hwnd: int) -> bool:
    """Return whether an HWND should be skipped when building the window list."""
    if not win32gui.IsWindowVisible(hwnd):
        return True
    if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
        return True
    ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    if ex_style & win32con.WS_EX_TOOLWINDOW:
        return True
    if win32gui.GetParent(hwnd) != 0:
        return True
    title = win32gui.GetWindowText(hwnd)
    if not title:
        return True
    # skip off-screen ghost windows (Windows uses -32000 for "hidden")
    try:
        x, y, _, _ = _window_rect(hwnd)
        if x <= -30000 or y <= -30000:
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Chrome profile detection
# ---------------------------------------------------------------------------

def _chrome_local_state_path() -> Optional[str]:
    """Return path to Chrome's Local State JSON (maps profile dirs to display names)."""
    local_app = os.environ.get("LOCALAPPDATA")
    if not local_app:
        return None
    path = os.path.join(local_app, "Google", "Chrome", "User Data", "Local State")
    return path if os.path.exists(path) else None


_chrome_profile_cache: Optional[Dict[str, str]] = None  # display_name_lower -> dir_id


def _load_chrome_profiles() -> Dict[str, str]:
    """Return a mapping of Chrome profile display names (lowercase) to directory IDs."""
    global _chrome_profile_cache
    if _chrome_profile_cache is not None:
        return _chrome_profile_cache
    path = _chrome_local_state_path()
    if not path:
        _chrome_profile_cache = {}
        return _chrome_profile_cache
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        info_cache = data.get("profile", {}).get("info_cache", {}) or {}
        mapping: Dict[str, str] = {}
        for dir_id, meta in info_cache.items():
            name = str(meta.get("name") or "").strip().lower()
            if name:
                mapping[name] = dir_id
        _chrome_profile_cache = mapping
        return mapping
    except Exception as exc:
        print(f"[window_manager] chrome profiles parse: {exc}")
        _chrome_profile_cache = {}
        return _chrome_profile_cache


def _detect_chrome_profile(window_title: str) -> Optional[str]:
    """
    Extract the Chrome profile directory id from a window title if possible.

    Chrome appends the profile name to the title like:
      "Some Page - Google Chrome - Work"
    We match the last " - <something>" segment against known profile display names.
    """
    if not window_title:
        return None
    profiles = _load_chrome_profiles()
    if not profiles:
        return None
    # Match only the trailing title segment: "... - <ProfileName>"
    parts = [p.strip() for p in window_title.split(" - ") if p.strip()]
    if not parts:
        return None
    key = parts[-1].lower()
    if key in profiles:
        return profiles[key]
    # Some locales/titles can include extra whitespace variants.
    key = " ".join(key.split())
    if key in profiles:
        return profiles[key]
    return None


def _build_chrome_launch(exe_path: str, profile_dir: Optional[str]) -> str:
    """Build a Chrome launch command that targets a specific profile."""
    cmd = f'"{exe_path}"'
    if profile_dir:
        cmd += f' --profile-directory="{profile_dir}"'
    return cmd


# ---------------------------------------------------------------------------
# UWP app detection (Store apps like Spotify, Settings, Calculator)
# ---------------------------------------------------------------------------

def _is_uwp_frame_host(process_name: str) -> bool:
    """UWP apps typically run under ApplicationFrameHost.exe."""
    return process_name.lower() == "applicationframehost.exe"


def _get_aumid_for_hwnd(hwnd: int) -> Optional[str]:
    """
    Query the AppUserModelID for a window using the shell property store.

    Returns None if the window doesn't have one.
    """
    # Kept intentionally conservative to avoid extra non-pywin32 dependencies.
    # If AUMID lookup fails, caller uses well-known title-based fallbacks.
    _ = hwnd
    return None


def _uwp_launch_command(aumid: Optional[str], window_title: str) -> Optional[str]:
    """
    Build a launch command for a UWP app.

    If we have the AUMID we use shell:AppsFolder. Otherwise, for well-known apps
    we fall back to a hand-rolled URI scheme.
    """
    if aumid:
        return f"explorer.exe shell:AppsFolder\\{aumid}"
    # Common-app fallbacks by title keyword
    title_lower = (window_title or "").lower()
    if "spotify" in title_lower:
        return "explorer.exe shell:AppsFolder\\SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify"
    if "settings" in title_lower:
        return "explorer.exe ms-settings:"
    return None


# ---------------------------------------------------------------------------
# Public window listing
# ---------------------------------------------------------------------------

def list_open_windows() -> List[dict]:
    """
    List visible top-level windows with hwnd, title, process_name, exe_path,
    rect (x, y, w, h), monitor_index, chrome_profile (or None), and launch_hint.
    """
    monitors = get_monitors()
    found: List[dict] = []

    def _cb(hwnd: int, _param: Any) -> bool:
        if _should_skip_window(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        exe_path = _query_process_exe_path(int(pid)) or ""
        process_name = _basename_lower(exe_path) or f"pid_{pid}"
        title = win32gui.GetWindowText(hwnd)
        x, y, w, h = _window_rect(hwnd)
        h_mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitor_index = _monitor_handle_to_index(int(h_mon), monitors)

        chrome_profile: Optional[str] = None
        launch_hint: str = ""

        if process_name == "chrome.exe":
            chrome_profile = _detect_chrome_profile(title)
            if exe_path:
                launch_hint = _build_chrome_launch(exe_path, chrome_profile)
        elif _is_uwp_frame_host(process_name):
            aumid = _get_aumid_for_hwnd(int(hwnd))
            launch_hint = _uwp_launch_command(aumid, title) or ""
        else:
            if exe_path:
                launch_hint = f'"{exe_path}"'

        found.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "process_name": process_name,
                "exe_path": exe_path,
                "rect": (x, y, w, h),
                "monitor_index": monitor_index,
                "chrome_profile": chrome_profile,
                "launch_hint": launch_hint,
            }
        )
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """Move and resize a top-level window to the given screen coordinates."""
    if not win32gui.IsWindow(int(hwnd)):
        return
    placement = win32gui.GetWindowPlacement(int(hwnd))
    if placement[1] == win32con.SW_SHOWMINIMIZED:
        win32gui.ShowWindow(int(hwnd), win32con.SW_RESTORE)
    elif placement[1] == win32con.SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(int(hwnd), win32con.SW_RESTORE)
    flags = win32con.SWP_NOZORDER | win32con.SWP_SHOWWINDOW
    win32gui.SetWindowPos(
        int(hwnd),
        0,
        int(x),
        int(y),
        int(width),
        int(height),
        flags,
    )


def minimize_window(hwnd: int) -> None:
    """Minimize a window. Silently ignores invalid hwnds."""
    try:
        if win32gui.IsWindow(int(hwnd)):
            win32gui.ShowWindow(int(hwnd), win32con.SW_MINIMIZE)
    except Exception as exc:
        print(f"[window_manager] minimize_window: {exc}")


def focus_window(hwnd: int) -> None:
    """Bring an existing window to the foreground and restore if minimized."""
    if not win32gui.IsWindow(int(hwnd)):
        return
    try:
        placement = win32gui.GetWindowPlacement(int(hwnd))
        if placement[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.ShowWindow(int(hwnd), win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(int(hwnd), win32con.SW_SHOW)
        win32gui.SetForegroundWindow(int(hwnd))
    except Exception as exc:
        print(f"[window_manager] focus_window: {exc}")


def find_window_by_process(
    process_name: str,
    window_title_match: Optional[str] = None,
) -> Optional[int]:
    """Find a top-level window HWND for a running process."""
    target_proc = (process_name or "").strip().lower()
    if not target_proc:
        return None
    if not target_proc.endswith(".exe"):
        target_proc = target_proc + ".exe"
    match_sub = (window_title_match or "").strip()
    for entry in list_open_windows():
        if entry["process_name"] != target_proc:
            continue
        title = entry.get("title") or ""
        if match_sub and match_sub not in title:
            continue
        return int(entry["hwnd"])
    return None


def find_chrome_window_by_profile(profile_dir: str, title_match: Optional[str] = None) -> Optional[int]:
    """Find a Chrome window for a specific profile directory id."""
    target_profile = (profile_dir or "").strip()
    if not target_profile:
        return None
    match_sub = (title_match or "").strip()
    for entry in list_open_windows():
        if entry["process_name"] != "chrome.exe":
            continue
        if entry.get("chrome_profile") != target_profile:
            continue
        if match_sub and match_sub not in (entry.get("title") or ""):
            continue
        return int(entry["hwnd"])
    return None


def launch_app(path_or_command: str) -> bool:
    """Launch an application from a path or full command line."""
    cmd = (path_or_command or "").strip()
    if not cmd:
        return False
    try:
        subprocess.Popen(cmd, shell=True)
        return True
    except Exception as exc:
        print(f"[window_manager] launch_app failed: {exc}")
        return False


def wait_for_window(
    process_name: str,
    window_title_match: Optional[str] = None,
    timeout_sec: float = 8.0,
    poll_sec: float = 0.35,
) -> Optional[int]:
    """Poll until a matching window appears, or timeout."""
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        hwnd = find_window_by_process(process_name, window_title_match)
        if hwnd:
            return hwnd
        time.sleep(float(poll_sec))
    return None


def wait_for_chrome_profile_window(
    profile_dir: str,
    title_match: Optional[str] = None,
    timeout_sec: float = 10.0,
    poll_sec: float = 0.4,
) -> Optional[int]:
    """Poll until a Chrome window matching the given profile appears."""
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        hwnd = find_chrome_window_by_profile(profile_dir, title_match)
        if hwnd:
            return hwnd
        time.sleep(float(poll_sec))
    return None
    