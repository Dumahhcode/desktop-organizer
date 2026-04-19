"""
System tray integration for Desktop Organizer using pystray and Pillow.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

import layouts
import pystray
import ui
from PIL import Image, ImageDraw


shutdown_event = threading.Event()
_tray_icon: Optional[pystray.Icon] = None


def _create_tray_image() -> Image.Image:
    """Build a simple tray icon image."""
    img = Image.new("RGBA", (64, 64), (30, 64, 120, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((4, 4, 60, 60), radius=10, outline=(180, 200, 255, 255), width=3)
    draw.text((22, 18), "D", fill=(230, 235, 255, 255))
    return img


def _apply_mode_async(mode_name: str) -> None:
    """Apply a layout mode on a short-lived daemon thread."""

    def _run() -> None:
        try:
            layouts.apply_mode(mode_name)
        except Exception as exc:
            print(f"[tray] apply_mode({mode_name!r}) failed: {exc}")

    threading.Thread(target=_run, daemon=True).start()


def _make_apply_mode_handler(mode_name: str):
    """
    Build a pystray-compatible ``(icon, item) -> None`` callback for one mode name.

    pystray only accepts actions with 0, 1, or 2 parameters, so we cannot use
    ``lambda icon, item, n=name`` (that counts as three parameters).
    """

    def _handler(icon: pystray.Icon, item: pystray.MenuItem) -> None:
        _apply_mode_async(mode_name)

    return _handler


def _build_apply_mode_submenu_items():
    """
    Return a tuple of MenuItems for the Apply Mode submenu.

    pystray re-invokes the single callable stored in ``Menu(callable)`` whenever
    it needs the item list, so this always reflects the current ``layouts.json``.
    A concrete tuple (not a generator) avoids Windows backends that iterate the
    sequence more than once.
    """
    names = layouts.get_mode_names()
    if not names:
        return (
            pystray.MenuItem(
                "No modes yet",
                lambda icon, item: None,
                enabled=False,
            ),
        )
    return tuple(
        pystray.MenuItem(name, _make_apply_mode_handler(name)) for name in names
    )


def _open_main(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Ask the UI thread to show the main organizer window."""
    try:
        ui.request_show_main()
    except Exception as exc:
        print(f"[tray] open main window failed: {exc}")


def _quit_app(icon: pystray.Icon, item: pystray.MenuItem) -> None:
    """Stop the tray icon and signal the main process to exit."""
    try:
        ui.request_shutdown()
    except Exception as exc:
        print(f"[tray] shutdown request failed: {exc}")
    shutdown_event.set()
    try:
        icon.stop()
    except Exception as exc:
        print(f"[tray] icon.stop failed: {exc}")


def _build_menu() -> pystray.Menu:
    """Construct the tray context menu."""
    return pystray.Menu(
        pystray.MenuItem("Open Desktop Organizer", _open_main),
        pystray.MenuItem("Apply Mode", pystray.Menu(_build_apply_mode_submenu_items)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _quit_app),
    )


def run_tray_icon(on_ready: Optional[Callable[[], None]] = None) -> None:
    """
    Run the tray icon until stopped. This call blocks the calling thread.

    on_ready, if provided, is invoked once immediately before the icon loop starts.
    """
    global _tray_icon
    image = _create_tray_image()
    menu = _build_menu()
    icon = pystray.Icon(
        "desktop_organizer",
        image,
        "Desktop Organizer",
        menu,
    )
    _tray_icon = icon
    if on_ready:
        try:
            on_ready()
        except Exception as exc:
            print(f"[tray] on_ready callback failed: {exc}")
    icon.run()


def stop_tray_icon() -> None:
    """Stop the tray icon if it is running."""
    global _tray_icon
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
        except Exception as exc:
            print(f"[tray] stop_tray_icon: {exc}")
        _tray_icon = None
