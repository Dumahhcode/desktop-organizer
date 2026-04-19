"""
Window and monitor helpers for Desktop Organizer using pywin32.
"""

from __future__ import annotations

import os
import subprocess
import time
from typing import Any, List, Optional, Tuple

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
except Exception:  # pragma: no cover - defensive for odd environments
    _KERNEL32 = None


def _query_process_exe_path(pid: int) -> Optional[str]:
    """
    Return the full executable path for a process id, or None if unavailable.
    """
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
    """
    Enumerate monitors as (handle, (left, top, right, bottom), is_primary).

    Uses pywin32's ``EnumDisplayMonitors()`` which returns a list of tuples
    ``(hMonitor, hdcMonitor, (left, top, right, bottom))``.
    """
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
            is_primary = bool(info.get("Flags", 0) & 1)  # MONITORINFOF_PRIMARY == 1
            results.append((int(h_monitor), (left, top, right, bottom), is_primary))
        except Exception as exc:
            print(f"[window_manager] GetMonitorInfo failed: {exc}")
            left, top, right, bottom = rect
            results.append((int(h_monitor), (left, top, right, bottom), False))
    return results


def get_monitors() -> List[dict]:
    """
    Return display monitors sorted left-to-right, then top-to-bottom.

    Each dict contains: index, x, y, width, height, is_primary, handle (HWND monitor).
    """
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
    return False


def list_open_windows() -> List[dict]:
    """
    List visible top-level windows as dicts with hwnd, title, process_name,
    rect (x, y, w, h), and monitor_index (based on get_monitors ordering).
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
        exe_path = _query_process_exe_path(int(pid))
        process_name = _basename_lower(exe_path) or f"pid_{pid}"
        title = win32gui.GetWindowText(hwnd)
        x, y, w, h = _window_rect(hwnd)
        h_mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
        monitor_index = _monitor_handle_to_index(int(h_mon), monitors)
        found.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "process_name": process_name,
                "rect": (x, y, w, h),
                "monitor_index": monitor_index,
            }
        )
        return True

    win32gui.EnumWindows(_cb, None)
    return found


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    """
    Move and resize a top-level window to the given screen coordinates.

    Restores the window first if it is minimized or maximized so the new
    geometry can take effect.
    """
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


def find_window_by_process(
    process_name: str,
    window_title_match: Optional[str] = None,
) -> Optional[int]:
    """
    Find a top-level window HWND for a running process.

    process_name is matched case-insensitively against the executable basename
    (for example, 'chrome.exe'). If window_title_match is provided, the window
    title must contain that substring.
    """
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


def launch_app(path_or_command: str) -> bool:
    """
    Launch an application from a path or full command line.

    Returns True if a launch was attempted without raising immediately; failures
    are still possible for invalid commands.
    """
    cmd = (path_or_command or "").strip()
    if not cmd:
        return False
    try:
        # Use shell on Windows so quoted paths and common flags work reliably.
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
    """
    Poll until a matching window appears, or timeout. Intended for post-launch waits.
    """
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        hwnd = find_window_by_process(process_name, window_title_match)
        if hwnd:
            return hwnd
        time.sleep(float(poll_sec))
    return None
