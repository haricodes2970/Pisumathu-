"""
pisumathu.py — Application entry point.

Wires AppController ↔ MainWindow ↔ PillOverlay.
All UI updates are marshalled through Tkinter's after() to stay on the
main thread; AppController callbacks are fired from worker threads.
"""

import tkinter as tk
import sys
import argparse
from typing import Optional

from config.settings import ConfigManager
from core.controller import AppController, AppState
from core.startup import set_startup_enabled, is_startup_enabled
from ui.main_window import MainWindow
from ui.pill import PillOverlay
from ui.tray import TrayManager


class PisumathuApp:
    """Root application class — bootstraps everything."""

    def __init__(self, launch_to_tray: bool = False):
        self.root = tk.Tk()
        self.root.withdraw()  # hide until ready
        self._quitting = False

        # Config
        self._cfg_mgr = ConfigManager()

        # Controller
        self._ctrl = AppController(self._cfg_mgr)
        self._ctrl.config.start_with_windows = is_startup_enabled()

        # UI
        self._main_win = MainWindow(
            root=self.root,
            config=self._ctrl.config,
            on_start=self._on_overlay_start,
            on_stop=self._on_overlay_stop,
            on_color_change=self._on_color_change,
            on_language_change=self._on_language_change,
            on_auto_type_change=self._on_auto_type_change,
            on_startup_change=self._on_startup_change,
            on_start_in_tray_change=self._on_start_in_tray_change,
            on_model_change=self._on_model_change,
        )
        self._pill: Optional[PillOverlay] = None
        self._tray = TrayManager(
            app_name="Pisumathu",
            on_open=self._on_tray_open,
            on_quit=self._on_tray_quit,
        )

        # Wire controller → UI callbacks
        self._ctrl.on_state_change = self._on_state_change
        self._ctrl.on_transcript = self._on_transcript
        self._ctrl.on_timer_tick = self._on_timer_tick
        self._ctrl.on_audio_level = self._on_audio_level
        self._ctrl.on_status = self._on_status_update

        # Show window then start background loading
        self.root.protocol("WM_DELETE_WINDOW", self._on_close_request)
        self._tray.start()

        should_launch_to_tray = launch_to_tray or bool(self._ctrl.config.start_in_tray)
        if should_launch_to_tray:
            self.root.withdraw()
            self._tray.notify("Pisumathu", "Running in system tray")
        else:
            self.root.deiconify()

        # Register our own HWND so the typer never types into Pisumathu itself
        self.root.update_idletasks()
        try:
            import ctypes
            own_hwnd = ctypes.windll.user32.GetForegroundWindow()
            self._ctrl.register_own_hwnd(own_hwnd)
        except Exception:
            pass

        self._ctrl.start()

    # ------------------------------------------------------------------
    # Overlay management
    # ------------------------------------------------------------------

    def _on_overlay_start(self) -> None:
        if self._pill is None or not self._pill.winfo_exists():
            self._pill = PillOverlay(self.root, self._ctrl.config)
            self._pill.set_state(self._ctrl.state)

    def _on_overlay_stop(self) -> None:
        if self._pill and self._pill.winfo_exists():
            self._pill.destroy_overlay()
            self._pill = None

    # ------------------------------------------------------------------
    # Controller callbacks (arrive from worker threads → marshal to UI)
    # ------------------------------------------------------------------

    def _on_state_change(self, state: AppState) -> None:
        self.root.after(0, self._apply_state, state)

    def _apply_state(self, state: AppState) -> None:
        self._main_win.set_state(state)
        if self._pill and self._pill.winfo_exists():
            self._pill.set_state(state)
        if state == AppState.IDLE and self._ctrl.device_label:
            self._main_win.set_model_ready(self._ctrl.device_label)

    def _on_transcript(self, text: str) -> None:
        self.root.after(0, self._main_win.append_transcript, text)

    def _on_timer_tick(self, label: str) -> None:
        self.root.after(0, self._apply_timer, label)

    def _apply_timer(self, label: str) -> None:
        if self._pill and self._pill.winfo_exists():
            self._pill.set_timer(label)

    def _on_audio_level(self, level: float) -> None:
        self.root.after(0, self._apply_level, level)

    def _apply_level(self, level: float) -> None:
        if self._pill and self._pill.winfo_exists():
            self._pill.set_audio_level(level)

    def _on_status_update(self, msg: str) -> None:
        self.root.after(0, self._main_win.set_status, msg)

    # ------------------------------------------------------------------
    # UI action callbacks
    # ------------------------------------------------------------------

    def _on_color_change(self, r: int, g: int, b: int) -> None:
        self._ctrl.update_color(r, g, b)
        if self._pill and self._pill.winfo_exists():
            self._pill.update_config(self._ctrl.config)

    def _on_language_change(self, lang: str) -> None:
        self._ctrl.set_language(lang)
        if self._pill and self._pill.winfo_exists():
            self._pill.update_config(self._ctrl.config)

    def _on_auto_type_change(self, enabled: bool) -> None:
        self._ctrl.set_auto_type(enabled)

    def _on_model_change(self, model_size: str) -> None:
        ok = self._ctrl.set_model_size(model_size)
        if ok:
            self._main_win.set_status(f"Using Whisper model: {model_size}")
        else:
            self._main_win.set_status("Model switch failed. Kept previous model.")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close_request(self) -> None:
        if not self._tray.is_running:
            self._shutdown()
            return
        self.root.withdraw()
        self._tray.notify("Pisumathu", "App minimized to system tray")

    def _shutdown(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self._on_overlay_stop()
        self._ctrl.stop()
        self._tray.stop()
        self.root.destroy()

    def _on_tray_open(self) -> None:
        self.root.after(0, self._show_window)

    def _show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _on_tray_quit(self) -> None:
        self.root.after(0, self._shutdown)

    def _on_startup_change(self, enabled: bool) -> None:
        applied = set_startup_enabled(enabled)
        if applied:
            self._ctrl.config.start_with_windows = enabled
            self._cfg_mgr.save(self._ctrl.config)
            self._main_win.set_status(
                "Startup enabled." if enabled else "Startup disabled."
            )
        else:
            self._main_win.set_status("Could not update Windows startup setting.")

    def _on_start_in_tray_change(self, enabled: bool) -> None:
        self._ctrl.config.start_in_tray = enabled
        self._cfg_mgr.save(self._ctrl.config)
        self._main_win.set_status(
            "Launch to tray enabled." if enabled else "Launch to tray disabled."
        )

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--tray", action="store_true", help="Launch minimized to tray")
    args, _ = parser.parse_known_args()

    app = PisumathuApp(launch_to_tray=args.tray)

    if app._ctrl.config.start_with_windows and not is_startup_enabled():
        set_startup_enabled(True)

    app.run()


if __name__ == "__main__":
    main()
