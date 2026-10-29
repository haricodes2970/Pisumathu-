"""Floating pill overlay.

Hidden while idle. Appears on the hotkey, shows recording, then transcribing,
then a confirmation. On Linux the window is an override-redirect XWayland
toplevel sized exactly to the pill, because Mutter does not implement
``wlr-layer-shell``.

``-transparentcolor`` is a Windows-only Tk attribute and is applied only
there; using it on X11 raises and would leave an opaque rectangle.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk

from ..state import AppState

BACKGROUND = "#14161c"
FOREGROUND = "#f2f4f8"
MUTED = "#9aa4b2"
RECORDING_COLOR = "#ff4d4f"
SUCCESS_COLOR = "#3ddc84"
ERROR_COLOR = "#ff7a45"
WINDOWS_TRANSPARENT = "#010101"

FONT_FAMILY = "DejaVu Sans"
WIDTH = 240
HEIGHT = 40
BOTTOM_MARGIN = 96

SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


class PillOverlay:
    """Small always-on-top capsule driven by :class:`AppState`."""

    def __init__(self, root: tk.Tk, on_copy_last=None, on_clear=None) -> None:
        self.root = root
        self._on_copy_last = on_copy_last
        self._on_clear = on_clear

        self._job: str | None = None
        self._state = AppState.IDLE
        self._record_started = 0.0
        self._blink = False
        self._spinner_index = 0

        background = BACKGROUND
        self.top = tk.Toplevel(root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        try:
            self.top.attributes("-topmost", True)
        except tk.TclError:
            pass
        try:
            self.top.attributes("-alpha", 0.94)
        except tk.TclError:
            pass

        if sys.platform == "win32":
            try:
                self.top.attributes("-transparentcolor", WINDOWS_TRANSPARENT)
                background = WINDOWS_TRANSPARENT
            except tk.TclError:
                background = BACKGROUND

        self._background = background
        self.top.configure(bg=background)

        self.container = tk.Frame(self.top, bg=background)
        self.container.pack(fill="both", expand=True)

        self.dot = tk.Canvas(
            self.container,
            width=12,
            height=12,
            bg=background,
            highlightthickness=0,
        )
        self.dot.pack(side="left", padx=(14, 8))
        self._dot_item = self.dot.create_oval(1, 1, 11, 11, fill=MUTED, outline="")

        self.label = tk.Label(
            self.container,
            text="",
            bg=background,
            fg=FOREGROUND,
            font=(FONT_FAMILY, 11),
            anchor="w",
        )
        self.label.pack(side="left", padx=(0, 14))

    # -- placement -----------------------------------------------------

    def _place(self) -> None:
        self.top.update_idletasks()
        screen_width = self.top.winfo_screenwidth()
        screen_height = self.top.winfo_screenheight()
        x = max(0, (screen_width - WIDTH) // 2)
        y = max(0, screen_height - HEIGHT - BOTTOM_MARGIN)
        self.top.geometry(f"{WIDTH}x{HEIGHT}+{x}+{y}")

    # -- state ---------------------------------------------------------

    def _cancel_job(self) -> None:
        if self._job is not None:
            try:
                self.top.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _set_dot(self, color: str) -> None:
        self.dot.itemconfigure(self._dot_item, fill=color)

    def set_state(self, state: AppState, detail: str = "") -> None:
        self._state = state
        self._cancel_job()

        if state is AppState.IDLE:
            self.top.withdraw()
            return

        if state is AppState.RECORDING:
            self._record_started = time.monotonic()
            self.label.configure(text="Recording  0.0s", fg=FOREGROUND)
            self._blink = True
            self._set_dot(RECORDING_COLOR)
            self._show()
            self._tick_recording()
            return

        if state is AppState.LOADING:
            self.label.configure(text="Loading model…", fg=MUTED)
            self._set_dot(MUTED)
        elif state is AppState.TRANSCRIBING:
            self._spinner_index = 0
            self.label.configure(text="Transcribing…", fg=FOREGROUND)
            self._set_dot(MUTED)
            self._show()
            self._tick_spinner()
            return
        elif state is AppState.COPIED:
            self.label.configure(text="✓ Copied", fg=SUCCESS_COLOR)
            self._set_dot(SUCCESS_COLOR)
        elif state is AppState.ERROR:
            message = detail or "Something went wrong"
            if len(message) > 34:
                message = message[:33] + "…"
            self.label.configure(text=f"! {message}", fg=ERROR_COLOR)
            self._set_dot(ERROR_COLOR)
        elif state is AppState.UNAVAILABLE:
            self.label.configure(text=detail or "Hotkey unavailable", fg=ERROR_COLOR)
            self._set_dot(ERROR_COLOR)
        else:
            self.label.configure(text=state.value, fg=FOREGROUND)
            self._set_dot(MUTED)

        self._show()

    def _show(self) -> None:
        self._place()
        try:
            self.top.deiconify()
            self.top.lift()
        except tk.TclError:
            pass

    # -- animation -----------------------------------------------------

    def _tick_recording(self) -> None:
        if self._state is not AppState.RECORDING:
            return
        elapsed = time.monotonic() - self._record_started
        self.label.configure(text=f"Recording  {elapsed:.1f}s")
        self._blink = not self._blink
        self._set_dot(RECORDING_COLOR if self._blink else "#7a2226")
        self._job = self.top.after(120, self._tick_recording)

    def _tick_spinner(self) -> None:
        if self._state is not AppState.TRANSCRIBING:
            return
        frame = SPINNER_FRAMES[self._spinner_index % len(SPINNER_FRAMES)]
        self._spinner_index += 1
        self.label.configure(text=f"{frame} Transcribing…")
        self._job = self.top.after(90, self._tick_spinner)

    # -- teardown ------------------------------------------------------

    def destroy(self) -> None:
        self._cancel_job()
        try:
            self.top.destroy()
        except tk.TclError:
            pass
