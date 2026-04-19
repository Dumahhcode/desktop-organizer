"""
References to the pywebview main window for tray actions and quit coordination.
"""

from __future__ import annotations

from typing import Any, Optional

_main_window: Optional[Any] = None
_force_quit: bool = False


def register_main_window(window: Any) -> None:
    """Store the primary pywebview window created in main."""
    global _main_window
    _main_window = window


def show_main_window() -> None:
    """Show and focus the organizer window (tray → Open)."""
    if _main_window is None:
        return
    try:
        _main_window.show()
    except Exception as exc:
        print(f"[window_control] show_main_window: {exc}")


def hide_main_window() -> None:
    """Hide the organizer window (minimize to tray)."""
    if _main_window is None:
        return
    try:
        _main_window.hide()
    except Exception as exc:
        print(f"[window_control] hide_main_window: {exc}")


def is_force_quit() -> bool:
    """Return True when the user chose Quit and the window should actually close."""
    return _force_quit


def request_quit() -> None:
    """
    Destroy the webview window so ``webview.start()`` can return and the process exit.

    May be invoked from the tray thread; failures are logged only.
    """
    global _force_quit, _main_window
    _force_quit = True
    try:
        import webview

        for w in list(webview.windows):
            try:
                w.destroy()
            except Exception as exc:
                print(f"[window_control] destroy window: {exc}")
    except Exception as exc:
        print(f"[window_control] request_quit: {exc}")
