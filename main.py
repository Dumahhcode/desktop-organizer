"""
Desktop Organizer entry point: tray icon, monitor watcher, and UI thread.
"""

from __future__ import annotations

import threading

import monitor
import tray
import ui


def main() -> None:
    """
    Start the UI thread, tray icon, and monitor watcher, then block until quit.

    The main CustomTkinter window stays hidden until opened from the tray menu.
    """
    ui.start_ui_thread()
    if not ui.wait_until_ui_ready():
        print("[main] UI thread did not become ready in time; exiting.")
        return

    threading.Thread(target=tray.run_tray_icon, daemon=True).start()

    def on_monitor_change(count: int) -> None:
        """Forward monitor topology changes to the UI thread."""
        try:
            ui.notify_monitor_change(count)
        except Exception as exc:
            print(f"[main] notify_monitor_change failed: {exc}")

    threading.Thread(
        target=lambda: monitor.watch_monitor_changes(on_monitor_change),
        daemon=True,
    ).start()

    print(
        "Desktop Organizer is running. Use the tray icon (blue 'D') — "
        "right-click for Open / Apply Mode / Quit."
    )
    tray.shutdown_event.wait()
    print("Shutting down...")
    ui_thread = ui.get_ui_thread()
    if ui_thread is not None and ui_thread.is_alive():
        ui.request_shutdown()
        ui_thread.join(timeout=12)


if __name__ == "__main__":
    main()
