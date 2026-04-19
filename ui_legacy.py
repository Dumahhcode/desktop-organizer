"""
CustomTkinter user interface for Desktop Organizer.

The UI owns a dedicated thread and a command queue so tray and monitor threads
can request windows without touching Tk widgets directly.
"""

from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

import layouts
import window_manager

_ui_queue: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
_ui_thread: Optional[threading.Thread] = None
_ready_event = threading.Event()
_app_instance: Optional["OrganizerApp"] = None


def request_show_main() -> None:
    """Ask the UI thread to show the main organizer window."""
    _ui_queue.put(("show", None))


def request_shutdown() -> None:
    """Ask the UI thread to shut down its main loop."""
    _ui_queue.put(("shutdown", None))


def notify_monitor_change(monitor_count: int) -> None:
    """Ask the UI thread to show the mode picker after a monitor topology change."""
    _ui_queue.put(("picker", int(monitor_count)))


def wait_until_ui_ready(timeout: float = 15.0) -> bool:
    """Block until the UI thread has created the root window, or timeout."""
    return _ready_event.wait(timeout=timeout)


def _pump_queue(app: "OrganizerApp") -> None:
    """
    Drain pending UI commands on the Tk thread and reschedule itself while alive.
    """
    try:
        while True:
            kind, payload = _ui_queue.get_nowait()
            if kind == "show":
                app._show_from_tray()
            elif kind == "shutdown":
                app._shutdown()
                return
            elif kind == "picker":
                app._open_mode_picker(int(payload))
    except queue.Empty:
        pass
    try:
        if app.winfo_exists():
            app.after(120, lambda: _pump_queue(app))
    except Exception:
        pass


def start_ui_thread() -> threading.Thread:
    """
    Start the CustomTkinter UI on a dedicated non-daemon thread.

    Returns the started thread handle so the caller can join on exit.
    """
    global _ui_thread

    def _run() -> None:
        global _app_instance
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        app = OrganizerApp()
        _app_instance = app
        _ready_event.set()
        app.after(80, lambda: _pump_queue(app))
        app.mainloop()
        _app_instance = None

    if _ui_thread and _ui_thread.is_alive():
        return _ui_thread
    _ready_event.clear()
    _ui_thread = threading.Thread(target=_run, name="desktop-organizer-ui", daemon=False)
    _ui_thread.start()
    return _ui_thread


def get_ui_thread() -> Optional[threading.Thread]:
    """Return the UI thread object if it was started."""
    return _ui_thread


class ModePickerWindow(ctk.CTkToplevel):
    """Small dialog listing modes to apply after the monitor count changes."""

    def __init__(self, master: ctk.CTk, monitor_count: int) -> None:
        """
        Create a mode picker dialog parented to the main CTk window.

        monitor_count is shown for context only.
        """
        super().__init__(master)
        self.title("Monitors changed")
        self.geometry("420x360")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self._configure_grab()

        ctk.CTkLabel(
            self,
            text=f"Monitor count is now {monitor_count}.\nPick a layout mode to apply:",
            wraplength=380,
        ).pack(padx=16, pady=(16, 8))

        body = ctk.CTkScrollableFrame(self, height=220)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        names = layouts.get_mode_names()
        if not names:
            ctk.CTkLabel(body, text="No modes defined yet.").pack(pady=8)

        for name in names:

            def _choose(n: str = name) -> None:
                self._apply_and_close(n)

            ctk.CTkButton(body, text=name, command=_choose).pack(fill="x", pady=4)

        ctk.CTkButton(self, text="Dismiss", command=self.destroy).pack(pady=(4, 16))

    def _configure_grab(self) -> None:
        """Raise the window and grab focus when possible."""
        try:
            self.transient(self.master)
        except Exception:
            pass
        self.lift()
        self.focus_force()
        try:
            self.grab_set()
        except Exception:
            pass

    def _apply_and_close(self, mode_name: str) -> None:
        """Apply the chosen mode on a worker thread, then close."""

        def _work() -> None:
            try:
                layouts.apply_mode(mode_name)
            except Exception as exc:
                print(f"[ui] mode picker apply failed: {exc}")

        threading.Thread(target=_work, daemon=True).start()
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


class AppEditorWindow(ctk.CTkToplevel):
    """Dialog to add or edit a single app entry within a mode."""

    def __init__(
        self,
        master: ctk.CTk,
        mode_name: str,
        app_index: Optional[int],
        initial: Optional[dict],
        on_saved: Callable[[], None],
    ) -> None:
        """
        Open the editor for a new app (app_index None) or an existing row index.
        """
        super().__init__(master)
        self._mode_name = mode_name
        self._app_index = app_index
        self._on_saved = on_saved
        self.title("Add App" if app_index is None else "Edit App")
        self.geometry("520x560")
        self.resizable(False, False)

        initial = initial or {}
        self._proc_manual = ctk.StringVar(value=str(initial.get("process_name", "")))
        self._title_match = ctk.StringVar(value=str(initial.get("window_title_match", "")))
        self._launch = ctk.StringVar(value=str(initial.get("launch_path", "")))

        mons = window_manager.get_monitors()
        mi = int(initial.get("monitor_index", 0))
        self._monitor_var = ctk.StringVar(value=str(mi if mons else 0))

        preset = str(initial.get("preset", "custom"))
        self._preset_var = ctk.StringVar(value=preset)

        pos = initial.get("position") or {}
        self._cx = ctk.StringVar(value=str(pos.get("x", 0)))
        self._cy = ctk.StringVar(value=str(pos.get("y", 0)))
        self._cw = ctk.StringVar(value=str(pos.get("width", 800)))
        self._ch = ctk.StringVar(value=str(pos.get("height", 600)))

        ctk.CTkLabel(self, text="Running windows").pack(anchor="w", padx=14, pady=(12, 2))
        row_pick = ctk.CTkFrame(self, fg_color="transparent")
        row_pick.pack(fill="x", padx=12)
        self._combo = ctk.CTkComboBox(row_pick, width=360, values=self._combo_values())
        self._combo.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row_pick, text="Refresh", width=80, command=self._refresh_combo).pack(
            side="left"
        )

        ctk.CTkLabel(self, text="Or type process / launch command manually").pack(
            anchor="w", padx=14, pady=(10, 2)
        )
        ctk.CTkEntry(self, textvariable=self._proc_manual).pack(fill="x", padx=12)

        ctk.CTkLabel(self, text="Window title contains (optional)").pack(
            anchor="w", padx=14, pady=(8, 2)
        )
        ctk.CTkEntry(self, textvariable=self._title_match).pack(fill="x", padx=12)

        ctk.CTkLabel(self, text="Launch path or command if not running (optional)").pack(
            anchor="w", padx=14, pady=(8, 2)
        )
        ctk.CTkEntry(self, textvariable=self._launch).pack(fill="x", padx=12)

        ctk.CTkLabel(self, text="Monitor").pack(anchor="w", padx=14, pady=(10, 2))
        mon_frame = ctk.CTkFrame(self, fg_color="transparent")
        mon_frame.pack(fill="x", padx=12)
        for m in mons:
            extra = ", primary" if m.get("is_primary") else ""
            label = f"{m['index']}  ({m['width']}x{m['height']}{extra})"
            ctk.CTkRadioButton(
                mon_frame,
                text=label,
                variable=self._monitor_var,
                value=str(m["index"]),
            ).pack(anchor="w")

        ctk.CTkLabel(self, text="Position preset").pack(anchor="w", padx=14, pady=(10, 2))
        preset_frame = ctk.CTkFrame(self, fg_color="transparent")
        preset_frame.pack(fill="x", padx=12)
        for label, val in (
            ("Left half", "left_half"),
            ("Right half", "right_half"),
            ("Top half", "top_half"),
            ("Bottom half", "bottom_half"),
            ("Maximized", "maximized"),
            ("Custom", "custom"),
        ):
            ctk.CTkRadioButton(
                preset_frame,
                text=label,
                variable=self._preset_var,
                value=val,
                command=self._toggle_custom,
            ).pack(anchor="w")

        self._custom_frame = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(self._custom_frame, text="Custom x").grid(row=0, column=0, padx=4, pady=2)
        ctk.CTkEntry(self._custom_frame, textvariable=self._cx, width=90).grid(
            row=0, column=1, padx=4
        )
        ctk.CTkLabel(self._custom_frame, text="y").grid(row=0, column=2, padx=4)
        ctk.CTkEntry(self._custom_frame, textvariable=self._cy, width=90).grid(
            row=0, column=3, padx=4
        )
        ctk.CTkLabel(self._custom_frame, text="w").grid(row=1, column=0, padx=4, pady=2)
        ctk.CTkEntry(self._custom_frame, textvariable=self._cw, width=90).grid(
            row=1, column=1, padx=4
        )
        ctk.CTkLabel(self._custom_frame, text="h").grid(row=1, column=2, padx=4)
        ctk.CTkEntry(self._custom_frame, textvariable=self._ch, width=90).grid(
            row=1, column=3, padx=4
        )

        self._toggle_custom()

        row_btn = ctk.CTkFrame(self, fg_color="transparent")
        row_btn.pack(fill="x", padx=12, pady=16)
        ctk.CTkButton(row_btn, text="Cancel", command=self.destroy).pack(
            side="right", padx=6
        )
        ctk.CTkButton(row_btn, text="Save", command=self._save).pack(side="right", padx=6)

        self._combo.configure(command=self._on_combo_pick)

    def _combo_values(self) -> List[str]:
        """Build combo box labels from open windows."""
        values: List[str] = []
        try:
            wins = window_manager.list_open_windows()
        except Exception as exc:
            print(f"[ui] list_open_windows failed: {exc}")
            return ["(unable to list windows)"]
        seen = set()
        for w in wins:
            proc = w.get("process_name") or ""
            title = (w.get("title") or "")[:80]
            key = (proc, title)
            if key in seen:
                continue
            seen.add(key)
            label = f"{proc} — {title}"
            values.append(label)
        return values or ["(no windows)"]

    def _refresh_combo(self) -> None:
        """Refresh the combo box from the current desktop state."""
        vals = self._combo_values()
        self._combo.configure(values=vals)
        if vals:
            self._combo.set(vals[0])

    def _on_combo_pick(self, choice: str) -> None:
        """When a window is chosen from the list, fill the process name field."""
        if " — " in choice:
            proc, _rest = choice.split(" — ", 1)
            self._proc_manual.set(proc.strip())

    def _toggle_custom(self) -> None:
        """Show or hide custom geometry fields based on the preset radio."""
        if self._preset_var.get() == "custom":
            if not self._custom_frame.winfo_ismapped():
                self._custom_frame.pack(fill="x", padx=12, pady=4)
        else:
            self._custom_frame.pack_forget()

    def _save(self) -> None:
        """Validate fields, persist, and close."""
        proc = self._proc_manual.get().strip()
        if not proc:
            print("[ui] process name is required")
            return
        proc_norm = proc.lower()
        if not proc_norm.endswith(".exe"):
            proc_norm = os.path.basename(proc_norm)
            if not proc_norm.endswith(".exe"):
                proc_norm = f"{proc_norm}.exe"
        try:
            mon_i = int(self._monitor_var.get())
        except Exception:
            mon_i = 0
        preset = self._preset_var.get()
        pos = {
            "x": int(float(self._cx.get() or 0)),
            "y": int(float(self._cy.get() or 0)),
            "width": int(float(self._cw.get() or 1)),
            "height": int(float(self._ch.get() or 1)),
        }
        cfg: Dict[str, Any] = {
            "process_name": proc_norm,
            "window_title_match": self._title_match.get().strip(),
            "launch_path": self._launch.get().strip(),
            "monitor_index": mon_i,
            "position": pos,
            "preset": preset,
        }
        ok = False
        try:
            if self._app_index is None:
                ok = layouts.add_app_to_mode(self._mode_name, cfg)
            else:
                ok = layouts.update_app_in_mode(self._mode_name, int(self._app_index), cfg)
        except Exception as exc:
            print(f"[ui] save app failed: {exc}")
        if ok:
            try:
                self._on_saved()
            except Exception as exc:
                print(f"[ui] on_saved callback failed: {exc}")
            self.destroy()
        else:
            print("[ui] could not save app entry")


class OrganizerApp(ctk.CTk):
    """Primary organizer window with mode list, preview, and app table."""

    def __init__(self) -> None:
        """Build widgets for the main organizer experience."""
        super().__init__()
        self.title("Desktop Organizer")
        self.geometry("1000x700")
        self.minsize(900, 600)

        self._selected_mode: Optional[str] = None
        self._mode_buttons: List[ctk.CTkButton] = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(sidebar, text="Modes", font=ctk.CTkFont(size=16, weight="bold")).pack(
            pady=(12, 6)
        )
        self._mode_list_frame = ctk.CTkScrollableFrame(sidebar, width=180, height=420)
        self._mode_list_frame.pack(fill="both", expand=True, padx=8, pady=4)

        ctk.CTkButton(sidebar, text="+ New Mode", command=self._new_mode).pack(
            fill="x", padx=10, pady=4
        )
        ctk.CTkButton(sidebar, text="Delete Mode", command=self._delete_mode).pack(
            fill="x", padx=10, pady=(4, 12)
        )

        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=10, pady=10)
        main.grid_rowconfigure(2, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self._header = ctk.CTkLabel(
            main,
            text="Select a mode",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        self._header.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self._preview_frame = ctk.CTkFrame(main, height=200)
        self._preview_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self._preview_frame.grid_propagate(False)
        self._preview_canvas = tk.Canvas(
            self._preview_frame,
            height=190,
            bg="#101010",
            highlightthickness=0,
        )
        self._preview_canvas.pack(fill="both", expand=True, padx=4, pady=4)
        self._preview_canvas.bind("<Configure>", self._on_preview_resize)

        self._apps_frame = ctk.CTkScrollableFrame(main)
        self._apps_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 8))

        bottom = ctk.CTkFrame(main, fg_color="transparent")
        bottom.grid(row=3, column=0, sticky="ew")
        ctk.CTkButton(bottom, text="+ Add App", command=self._add_app).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(bottom, text="Apply Now", command=self._apply_now).pack(
            side="left", padx=4
        )
        ctk.CTkButton(bottom, text="Capture Current Layout", command=self._capture_layout).pack(
            side="left", padx=4
        )

        self.protocol("WM_DELETE_WINDOW", self._on_user_close)
        self.withdraw()
        self._refresh_mode_list()

    def _on_user_close(self) -> None:
        """Hide instead of destroying so the tray can reopen the same window."""
        self.withdraw()

    def _show_from_tray(self) -> None:
        """Show and focus the organizer window."""
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _shutdown(self) -> None:
        """Destroy the Tk hierarchy and end the UI thread."""
        try:
            self.quit()
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _open_mode_picker(self, monitor_count: int) -> None:
        """Present the post-dock mode chooser as a transient dialog."""
        try:
            self.deiconify()
        except Exception:
            pass
        try:
            ModePickerWindow(self, monitor_count)
        except Exception as exc:
            print(f"[ui] mode picker failed: {exc}")

    def _refresh_mode_list(self) -> None:
        """Rebuild the sidebar mode buttons from disk."""
        for w in self._mode_list_frame.winfo_children():
            w.destroy()
        self._mode_buttons.clear()
        for name in layouts.get_mode_names():

            def _sel(n: str = name) -> None:
                self._select_mode(n)

            btn = ctk.CTkButton(
                self._mode_list_frame,
                text=name,
                anchor="w",
                command=_sel,
            )
            btn.pack(fill="x", pady=3)
            self._mode_buttons.append(btn)
        self._update_mode_highlight()

    def _update_mode_highlight(self) -> None:
        """Emphasize the currently selected mode button."""
        for btn in self._mode_buttons:
            if btn.cget("text") == self._selected_mode:
                btn.configure(fg_color=("gray75", "gray25"))
            else:
                btn.configure(fg_color=("gray70", "gray30"))

    def _select_mode(self, name: str) -> None:
        """Select a mode and refresh the main panel."""
        self._selected_mode = name
        self._header.configure(text=f"Mode: {name}")
        self._update_mode_highlight()
        self._reload_apps_panel()
        self._draw_monitor_preview()

    def _reload_apps_panel(self) -> None:
        """Render app rows for the selected mode."""
        for w in self._apps_frame.winfo_children():
            w.destroy()
        mode = layouts.get_mode(self._selected_mode or "")
        if not mode:
            ctk.CTkLabel(self._apps_frame, text="Select a mode from the left.").pack(
                anchor="w", pady=6
            )
            return
        apps = mode.get("apps") or []
        if not apps:
            ctk.CTkLabel(self._apps_frame, text="No apps in this mode yet.").pack(
                anchor="w", pady=6
            )
            return
        header = ctk.CTkFrame(self._apps_frame, fg_color="transparent")
        header.pack(fill="x", pady=(0, 4))
        for col, text, w in (
            (0, "Process", 160),
            (1, "Monitor", 60),
            (2, "Preset", 120),
            (3, "Title match", 220),
            (4, "", 160),
        ):
            ctk.CTkLabel(header, text=text, width=w, anchor="w").grid(
                row=0, column=col, padx=4, sticky="w"
            )
        for idx, app in enumerate(apps):
            row = ctk.CTkFrame(self._apps_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkLabel(
                row,
                text=str(app.get("process_name", "")),
                width=160,
                anchor="w",
            ).grid(row=0, column=0, padx=4)
            ctk.CTkLabel(
                row,
                text=str(app.get("monitor_index", "")),
                width=60,
                anchor="w",
            ).grid(row=0, column=1, padx=4)
            ctk.CTkLabel(
                row,
                text=str(app.get("preset", "")),
                width=120,
                anchor="w",
            ).grid(row=0, column=2, padx=4)
            tm = str(app.get("window_title_match", ""))[:40]
            ctk.CTkLabel(row, text=tm, width=220, anchor="w").grid(row=0, column=3, padx=4)

            def _edit(i: int = idx) -> None:
                self._edit_app(i)

            def _delete(i: int = idx) -> None:
                self._delete_app(i)

            bf = ctk.CTkFrame(row, fg_color="transparent", width=160)
            bf.grid(row=0, column=4, padx=4)
            ctk.CTkButton(bf, text="Edit", width=70, command=_edit).pack(
                side="left", padx=2
            )
            ctk.CTkButton(bf, text="Delete", width=70, command=_delete).pack(
                side="left", padx=2
            )

    def _on_preview_resize(self, _evt: Any = None) -> None:
        """Redraw the scaled monitor preview when the canvas size changes."""
        self._draw_monitor_preview()

    def _draw_monitor_preview(self) -> None:
        """Draw monitors and app rectangles on the preview canvas."""
        canvas = self._preview_canvas
        canvas.delete("all")
        mons = window_manager.get_monitors()
        if not mons:
            canvas.create_text(
                10,
                10,
                anchor="nw",
                fill="#888888",
                text="No monitors detected",
            )
            return
        mode = layouts.get_mode(self._selected_mode or "")
        apps = (mode or {}).get("apps") or []

        min_x = min(m["x"] for m in mons)
        min_y = min(m["y"] for m in mons)
        max_x = max(m["x"] + m["width"] for m in mons)
        max_y = max(m["y"] + m["height"] for m in mons)
        total_w = max(1, max_x - min_x)
        total_h = max(1, max_y - min_y)

        cw = max(2, canvas.winfo_width())
        ch = max(2, canvas.winfo_height())
        pad = 12
        scale = min((cw - 2 * pad) / total_w, (ch - 2 * pad) / total_h)

        def sx(x: float) -> float:
            return pad + (x - min_x) * scale

        def sy(y: float) -> float:
            return pad + (y - min_y) * scale

        for m in mons:
            x1, y1, x2, y2 = sx(m["x"]), sy(m["y"]), sx(m["x"] + m["width"]), sy(
                m["y"] + m["height"]
            )
            canvas.create_rectangle(x1, y1, x2, y2, outline="#555555", width=2)
            if m.get("is_primary"):
                canvas.create_text(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2,
                    text="Primary",
                    fill="#666666",
                )

        for app in apps:
            try:
                mi = int(app.get("monitor_index", 0))
            except Exception:
                mi = 0
            bounds = None
            for mon in mons:
                if int(mon["index"]) == mi:
                    bounds = (mon["x"], mon["y"], mon["width"], mon["height"])
                    break
            if not bounds:
                bounds = (mons[0]["x"], mons[0]["y"], mons[0]["width"], mons[0]["height"])
            rect = layouts.rect_for_preset(
                bounds,
                str(app.get("preset", "custom")),
                app.get("position") if isinstance(app.get("position"), dict) else {},
            )
            x, y, w, h = rect
            x1, y1, x2, y2 = sx(x), sy(y), sx(x + w), sy(y + h)
            canvas.create_rectangle(
                x1,
                y1,
                x2,
                y2,
                outline="#4aa3ff",
                width=2,
                dash=(4, 2),
            )

    def _new_mode(self) -> None:
        """Prompt for a new mode name and persist it."""
        dialog = ctk.CTkInputDialog(text="Mode name:", title="New Mode")
        name = (dialog.get_input() or "").strip()
        if not name:
            return
        if layouts.add_mode(name):
            self._refresh_mode_list()
            self._select_mode(name)
        else:
            print(f"[ui] could not add mode {name!r} (duplicate or invalid)")

    def _delete_mode(self) -> None:
        """Delete the selected mode after basic confirmation."""
        name = self._selected_mode
        if not name:
            print("[ui] select a mode to delete")
            return
        if layouts.delete_mode(name):
            self._selected_mode = None
            self._header.configure(text="Select a mode")
            self._refresh_mode_list()
            self._reload_apps_panel()
            self._draw_monitor_preview()
        else:
            print("[ui] delete_mode failed")

    def _add_app(self) -> None:
        """Open the add-app dialog for the current mode."""
        if not self._selected_mode:
            print("[ui] select a mode first")
            return
        AppEditorWindow(self, self._selected_mode, None, None, self._after_app_saved)

    def _edit_app(self, index: int) -> None:
        """Open the editor for an existing app row."""
        if not self._selected_mode:
            return
        mode = layouts.get_mode(self._selected_mode)
        apps = (mode or {}).get("apps") or []
        if index < 0 or index >= len(apps):
            return
        AppEditorWindow(
            self,
            self._selected_mode,
            index,
            dict(apps[index]),
            self._after_app_saved,
        )

    def _delete_app(self, index: int) -> None:
        """Remove an app row and refresh."""
        if not self._selected_mode:
            return
        if layouts.remove_app_from_mode(self._selected_mode, index):
            self._reload_apps_panel()
            self._draw_monitor_preview()
        else:
            print("[ui] remove_app_from_mode failed")

    def _after_app_saved(self) -> None:
        """Refresh lists after the editor saves."""
        self._reload_apps_panel()
        self._draw_monitor_preview()

    def _apply_now(self) -> None:
        """Apply the current mode on a worker thread."""
        name = self._selected_mode
        if not name:
            print("[ui] select a mode before applying")
            return

        def _work() -> None:
            try:
                layouts.apply_mode(name)
            except Exception as exc:
                print(f"[ui] apply_mode failed: {exc}")

        threading.Thread(target=_work, daemon=True).start()

    def _capture_layout(self) -> None:
        """Snapshot open windows into the selected mode without blocking the UI."""

        name = self._selected_mode
        if not name:
            print("[ui] select a mode before capturing")

            return

        def _work() -> None:
            try:
                count = layouts.capture_current_layout_to_mode(name)
            except Exception as exc:
                print(f"[ui] capture failed: {exc}")
                count = -1

            def _done() -> None:
                if count >= 0:
                    self._reload_apps_panel()
                    self._draw_monitor_preview()
                    print(f"[ui] captured {count} windows into mode {name!r}")

            self.after(0, _done)

        threading.Thread(target=_work, daemon=True).start()
