import ctypes
import time


def get_monitor_count():
    """
    Return the number of display monitors attached to the desktop.

    Uses ``GetSystemMetrics(SM_CMONITORS)`` via ``ctypes``.
    """
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(80)  # SM_CMONITORS = 80


def watch_monitor_changes(callback):
    """
    Poll monitor count every two seconds and invoke ``callback`` with the new count when it changes.

    Blocks forever; intended to be run on a background thread.
    """
    last_count = get_monitor_count()
    while True:
        time.sleep(2)
        current_count = get_monitor_count()
        if current_count != last_count:
            last_count = current_count
            callback(current_count)