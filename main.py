"""
Desktop Organizer entry point: pywebview UI, tray icon, and monitor watcher.

``webview.start()`` runs on the main thread (required by pywebview on Windows).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import monitor
import tray
import webview
import window_control
from bridge import Bridge


def _get_base_path() -> Path:
    """
    Return the folder that contains bundled resources (frontend, layouts.json).

    When running as a PyInstaller .exe, resources live in a temporary directory
    exposed by ``sys._MEIPASS``. When running as a normal script, they live next
    to this file.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _notify_monitor_js(count: int) -> None:
    """Tell the frontend to open the in-page monitor / mode picker."""
    try:
        payload = json.dumps({"count": int(count)})
        for win in webview.windows:
            win.evaluate_js(
                f"window.__onMonitorChanged&&window.__onMonitorChanged({payload})"
            )
    except Exception as exc:
        print(f"[main] monitor JS notify: {exc}")


def _on_window_closing(window) -> bool:
    """
    Hide to tray instead of destroying, unless ``request_quit`` set force quit.

    Returning ``False`` cancels the close (pywebview collects ``False`` returns).
    """
    if window_control.is_force_quit():
        return True
    try:
        window.hide()
    except Exception as exc:
        print(f"[main] hide on close: {exc}")
    return False


def _monitor_worker() -> None:
    """Poll monitor count and notify the webview when it changes."""

    def _cb(count: int) -> None:
        _notify_monitor_js(count)

    monitor.watch_monitor_changes(_cb)


def main() -> None:
    """Create the webview window, register tray + monitor threads, then run the GUI loop."""
    bridge = Bridge()
    base_path = _get_base_path()
    html_path = base_path / "frontend" / "index.html"
    url = html_path.as_uri()

    window = webview.create_window(
        "desktop organizer",
        url=url,
        js_api=bridge,
        width=1100,
        height=720,
        min_size=(900, 600),
        hidden=True,
        background_color="#0d0d0f",
        text_select=True,
    )
    window_control.register_main_window(window)
    window.events.closing += _on_window_closing

    threading.Thread(target=tray.run_tray_icon, daemon=True).start()
    threading.Thread(target=_monitor_worker, daemon=True).start()

    print(
        "desktop organizer — tray icon (use open). webview starts hidden; "
        "quit from tray destroys the window."
    )
    webview.start(debug=False)
    print("webview closed; exiting.")


if __name__ == "__main__":
    main()