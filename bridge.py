"""
Python API exposed to the pywebview frontend (js_api).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Optional

import layouts
import monitor
import window_control
import window_manager

_last_applied: Dict[str, float] = {}
_last_applied_lock = threading.Lock()


def _serializable_monitors() -> List[dict]:
    """Return monitor dicts safe for JSON (drop non-primitive handles)."""
    out: List[dict] = []
    for m in window_manager.get_monitors():
        out.append(
            {
                "index": int(m["index"]),
                "x": int(m["x"]),
                "y": int(m["y"]),
                "width": int(m["width"]),
                "height": int(m["height"]),
                "is_primary": bool(m.get("is_primary")),
            }
        )
    return out


def _serializable_windows() -> List[dict]:
    """Return open-window dicts without HWND if preferred — keep hwnd for UI."""
    rows: List[dict] = []
    for w in window_manager.list_open_windows():
        rows.append(
            {
                "hwnd": int(w["hwnd"]),
                "title": str(w.get("title") or ""),
                "process_name": str(w.get("process_name") or ""),
                "rect": list(w.get("rect") or (0, 0, 0, 0)),
                "monitor_index": int(w.get("monitor_index", 0)),
                "launch_hint": str(w.get("launch_hint") or ""),
                "chrome_profile": w.get("chrome_profile"),
            }
        )
    return rows


class Bridge:
    """
    Instance methods are exposed to JavaScript via ``window.pywebview.api``.

    pywebview invokes each call on a worker thread; long work should still be
    offloaded explicitly where noted (e.g. ``apply_mode``).
    """

    def get_modes(self) -> dict:
        """Return the full layouts document (same shape as ``layouts.json``)."""
        return layouts.load_layouts()

    def get_mode(self, name: str) -> Optional[dict]:
        """Return one mode dict or ``None``."""
        return layouts.get_mode(name or "")

    def create_mode(self, name: str) -> dict:
        """Create an empty mode. Returns ``{ok, error?}``."""
        ok = layouts.add_mode(name or "")
        if ok:
            return {"ok": True}
        return {"ok": False, "error": "duplicate or empty name"}

    def delete_mode(self, name: str) -> dict:
        """Delete a mode by name."""
        ok = layouts.delete_mode(name or "")
        return {"ok": bool(ok)}

    def rename_mode(self, old_name: str, new_name: str) -> dict:
        """Rename a mode."""
        ok = layouts.rename_mode(old_name or "", new_name or "")
        if ok:
            return {"ok": True}
        return {"ok": False, "error": "invalid or duplicate name"}

    def add_app_to_mode(self, mode_name: str, app_config: dict) -> dict:
        """Append an app row to a mode."""
        cfg = app_config if isinstance(app_config, dict) else {}
        ok = layouts.add_app_to_mode(mode_name or "", cfg)
        return {"ok": bool(ok)}

    def update_app_in_mode(self, mode_name: str, index: int, app_config: dict) -> dict:
        """Replace app at index."""
        cfg = app_config if isinstance(app_config, dict) else {}
        try:
            idx = int(index)
        except Exception:
            return {"ok": False, "error": "bad index"}
        ok = layouts.update_app_in_mode(mode_name or "", idx, cfg)
        return {"ok": bool(ok)}

    def remove_app_from_mode(self, mode_name: str, index: int) -> dict:
        """Remove app at index."""
        try:
            idx = int(index)
        except Exception:
            return {"ok": False, "error": "bad index"}
        ok = layouts.remove_app_from_mode(mode_name or "", idx)
        return {"ok": bool(ok)}

    def apply_mode(self, name: str) -> dict:
        """
        Apply a mode on a daemon thread and return immediately.

        Records ``last_applied`` timestamp for dashboard stats.
        """

        def _run() -> None:
            try:
                layouts.apply_mode(name or "")
                with _last_applied_lock:
                    _last_applied[(name or "").strip()] = time.time()
            except Exception as exc:
                print(f"[bridge] apply_mode: {exc}")

        threading.Thread(target=_run, daemon=True).start()
        return {"ok": True}

    def capture_current_layout(self, mode_name: str) -> dict:
        """Snapshot open windows into the named mode."""
        try:
            n = layouts.capture_current_layout_to_mode(mode_name or "")
            return {"ok": True, "count": int(n)}
        except Exception as exc:
            print(f"[bridge] capture_current_layout: {exc}")
            return {"ok": False, "error": str(exc)}

    def get_open_windows(self) -> List[dict]:
        """List visible top-level windows for the add-app dialog."""
        try:
            return _serializable_windows()
        except Exception as exc:
            print(f"[bridge] get_open_windows: {exc}")
            return []

    def get_monitors(self) -> List[dict]:
        """Monitor rectangles for layout preview."""
        try:
            return _serializable_monitors()
        except Exception as exc:
            print(f"[bridge] get_monitors: {exc}")
            return []

    def get_monitor_count(self) -> int:
        """Current SM_CMONITORS-style count."""
        try:
            return int(monitor.get_monitor_count())
        except Exception as exc:
            print(f"[bridge] get_monitor_count: {exc}")
            return 0

    def get_mode_stats(self, mode_name: str) -> dict:
        """
        Dashboard fields: relative last apply time, app count, monitor count.
        """
        name = (mode_name or "").strip()
        mode = layouts.get_mode(name)
        app_count = len(mode.get("apps", [])) if mode else 0
        with _last_applied_lock:
            ts = _last_applied.get(name)
        if ts is None:
            last_label = "never"
        else:
            delta = max(0, int(time.time() - ts))
            if delta < 60:
                last_label = f"{delta}s_ago"
            elif delta < 3600:
                last_label = f"{delta // 60}m_ago"
            else:
                last_label = f"{delta // 3600}h_ago"
        return {
            "last_applied": last_label,
            "apps": app_count,
            "monitors": len(_serializable_monitors()),
        }

    def get_quick_launch(self) -> List[dict]:
        """Return quick launch entries."""
        return layouts.get_quick_launch()

    def add_quick_launch(self, app_config: dict) -> dict:
        """Add a quick launch entry."""
        cfg = app_config if isinstance(app_config, dict) else {}
        ok = layouts.add_quick_launch(cfg)
        return {"ok": bool(ok)}

    def remove_quick_launch(self, index: int) -> dict:
        """Remove quick launch entry by index."""
        try:
            idx = int(index)
        except Exception:
            return {"ok": False, "error": "bad index"}
        ok = layouts.remove_quick_launch(idx)
        return {"ok": bool(ok)}

    def update_quick_launch(self, index: int, app_config: dict) -> dict:
        """Update quick launch entry by index."""
        try:
            idx = int(index)
        except Exception:
            return {"ok": False, "error": "bad index"}
        cfg = app_config if isinstance(app_config, dict) else {}
        ok = layouts.update_quick_launch(idx, cfg)
        return {"ok": bool(ok)}

    def launch_or_focus(self, index: int) -> dict:
        """Launch or focus a quick launch entry."""
        return layouts.launch_or_focus(index)

    def minimize_to_tray(self) -> dict:
        """Hide the webview window (same as closing to tray)."""
        try:
            window_control.hide_main_window()
            return {"ok": True}
        except Exception as exc:
            print(f"[bridge] minimize_to_tray: {exc}")
            return {"ok": False, "error": str(exc)}
