"""
pisumathu.py — Application entry point.

Wires AppController ↔ MainWindow ↔ PillOverlay.
All UI updates are marshalled through Tkinter's after() to stay on the
main thread; AppController callbacks are fired from worker threads.
"""

import tkinter as tk
import sys
import threading
from typing import Optional

from config.settings import ConfigManager
from core.controller import AppController, AppState
from ui.main_window import MainWindow
from ui.pill import PillOverlay


class PisumathuApp:
    """Root application class — bootstraps everything."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()  # hide until ready

        # Config
        self._cfg_mgr = ConfigManager()

        # Controller
        self._ctrl = AppController(self._cfg_mgr)

        # UI
        self._main_win = MainWindow(
            root=self.root,
            config=self._ctrl.config,
            on_start=self._on_overlay_start,
            on_stop=self._on_overlay_stop,
            on_color_change=self._on_color_change,
            on_language_change=self._on_language_change,
            on_auto_type_change=self._on_auto_type_change,
        )
        self._pill: Optional[PillOverlay] = None

        # Wire controller → UI callbacks
        self._ctrl.on_state_change = self._on_state_change
        self._ctrl.on_transcript = self._on_transcript
        self._ctrl.on_timer_tick = self._on_timer_tick
        self._ctrl.on_audio_level = self._on_audio_level
        self._ctrl.on_status = self._on_status_update

        # Show window then start background loading
        self.root.deiconify()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self._on_overlay_stop()
        self._ctrl.stop()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = PisumathuApp()
    app.run()


if __name__ == "__main__":
    main()
