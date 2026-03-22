"""
ui/pill.py — Floating pill overlay window.

Always-on-top, borderless, transparent-background pill.
Three states: IDLE → RECORDING → TRANSCRIBING
"""

import tkinter as tk
import math
import time
import threading
from typing import Optional

from core.controller import AppState
from config.settings import AppConfig


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
PILL_H = 44
PILL_PADDING_X = 16
PILL_PADDING_Y = 8
BAR_COUNT = 8
BAR_W = 3
BAR_GAP = 2
DOT_R = 5
FONT_NAME_EN = ("Courier New", 11, "bold")
FONT_NAME_KN = ("Noto Sans Kannada", 11, "bold")
FONT_TIMER = ("Courier New", 10, "bold")
FONT_STATUS = ("Courier New", 9)

IDLE_W = 170
RECORDING_W = 320
TRANSCRIBING_W = 220

BG_PILL_LIGHT = "#f5f7fa"
TEXT_MUTED = "#9ca3af"
RED_DOT = "#ef4444"


class PillOverlay(tk.Toplevel):
    """
    The floating pill UI widget.

    Receives state updates and config via public methods — never reads
    from the controller directly to keep UI decoupled.
    """

    def __init__(self, master: tk.Tk, config: AppConfig):
        super().__init__(master)
        self.config_ref = config

        # Window chrome
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-transparentcolor", "#010101")
        self.configure(bg="#010101")

        # Internal state
        self._state = AppState.IDLE
        self._timer_text = "00:00"
        self._audio_level = 0.0
        self._bar_heights = [4.0] * BAR_COUNT
        self._spinner_angle = 0.0
        self._blink_on = True

        # Canvas
        self._canvas = tk.Canvas(
            self,
            bg="#010101",
            highlightthickness=0,
            cursor="arrow",
        )
        self._canvas.pack(fill="both", expand=True)

        # Position at bottom-center
        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()
        self._position_pill(IDLE_W)

        # Start render loop
        self._running = True
        self._anim_thread = threading.Thread(target=self._anim_loop, daemon=True)
        self._anim_thread.start()
        self._render()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state: AppState) -> None:
        self._state = state
        if state == AppState.IDLE:
            self._timer_text = "00:00"

    def set_timer(self, text: str) -> None:
        self._timer_text = text

    def set_audio_level(self, level: float) -> None:
        self._audio_level = level

    def update_config(self, config: AppConfig) -> None:
        self.config_ref = config

    def destroy_overlay(self) -> None:
        self._running = False
        self.destroy()

    # ------------------------------------------------------------------
    # Animation thread (updates bar heights + spinner angle)
    # ------------------------------------------------------------------

    def _anim_loop(self) -> None:
        t = 0.0
        while self._running:
            if self._state == AppState.RECORDING:
                # Animate waveform bars
                for i in range(BAR_COUNT):
                    phase = t * 6.0 + i * 0.8
                    base = 4.0 + 10.0 * self._audio_level
                    variation = math.sin(phase) * 5.0 * self._audio_level
                    self._bar_heights[i] = max(2.0, min(14.0, base + variation))
                self._blink_on = (int(t * 2.5) % 2) == 0
            elif self._state == AppState.TRANSCRIBING:
                self._spinner_angle = (t * 360.0) % 360.0
            else:
                for i in range(BAR_COUNT):
                    self._bar_heights[i] = 3.0
            t += 0.05
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def _render(self) -> None:
        if not self._running:
            return
        try:
            self._draw()
        except tk.TclError:
            return
        self.after(40, self._render)  # ~25 fps

    def _draw(self) -> None:
        state = self._state
        cfg = self.config_ref

        accent = cfg.accent_hex()
        tint = cfg.light_tint_hex()
        shade = cfg.dark_shade_hex()
        lang = cfg.language

        if state == AppState.RECORDING:
            w = RECORDING_W
        elif state == AppState.TRANSCRIBING:
            w = TRANSCRIBING_W
        else:
            w = IDLE_W

        h = PILL_H
        self._position_pill(w)
        self._canvas.config(width=w, height=h)
        self.geometry(f"{w}x{h}")
        c = self._canvas
        c.delete("all")

        # Pill background
        r = h // 2
        self._draw_pill(c, 0, 0, w, h, r, fill=tint, outline=accent, width=1)

        cx = PILL_PADDING_X
        cy = h // 2

        if state == AppState.IDLE:
            # Dim dot
            c.create_oval(cx - DOT_R, cy - DOT_R, cx + DOT_R, cy + DOT_R,
                          fill=TEXT_MUTED, outline="")
            cx += DOT_R * 2 + 6
            # Name
            name = self._name_text(lang)
            c.create_text(cx, cy, text=name, anchor="w",
                          font=self._name_font(lang), fill=TEXT_MUTED)

        elif state == AppState.RECORDING:
            # Red blinking dot
            dot_color = RED_DOT if self._blink_on else "#7f2222"
            c.create_oval(cx - DOT_R, cy - DOT_R, cx + DOT_R, cy + DOT_R,
                          fill=dot_color, outline="")
            cx += DOT_R * 2 + 6

            # Waveform bars
            for i, bh in enumerate(self._bar_heights):
                bx = cx + i * (BAR_W + BAR_GAP)
                by_top = cy - bh
                by_bot = cy + bh
                c.create_rectangle(bx, by_top, bx + BAR_W, by_bot,
                                   fill=accent, outline="")
            cx += BAR_COUNT * (BAR_W + BAR_GAP) + 8

            # Name
            name = self._name_text(lang)
            c.create_text(cx, cy, text=name, anchor="w",
                          font=self._name_font(lang), fill=shade)
            name_w = self._text_width(name, self._name_font(lang))
            cx += name_w + 10

            # Timer (right-aligned)
            c.create_text(w - PILL_PADDING_X, cy, text=self._timer_text,
                          anchor="e", font=FONT_TIMER, fill=shade)

        elif state == AppState.TRANSCRIBING:
            # Spinner arc
            sa = self._spinner_angle
            sr = 8
            c.create_arc(cx - sr, cy - sr, cx + sr, cy + sr,
                         start=sa, extent=270, outline=accent,
                         width=2, style="arc")
            cx += sr * 2 + 8
            c.create_text(cx, cy, text="processing...", anchor="w",
                          font=FONT_STATUS, fill=shade)

        elif state == AppState.LOADING:
            c.create_text(w // 2, cy, text="loading model…",
                          anchor="center", font=FONT_STATUS, fill=TEXT_MUTED)

    def _draw_pill(self, c, x1, y1, x2, y2, r, fill, outline, width):
        """Draw a pill/rounded-rect on canvas."""
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        c.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=width)

    def _position_pill(self, w: int) -> None:
        x = (self._screen_w - w) // 2
        y = self._screen_h - PILL_H - 40  # 40px above taskbar
        self.geometry(f"{w}x{PILL_H}+{x}+{y}")

    @staticmethod
    def _name_text(lang: str) -> str:
        return "ಪಿಸುಮಾಥು" if lang == "kn" else "PISUMATHU"

    @staticmethod
    def _name_font(lang: str):
        return FONT_NAME_KN if lang == "kn" else FONT_NAME_EN

    def _text_width(self, text: str, font) -> int:
        """Approximate text width in pixels."""
        try:
            f = tk.font.Font(font=font)
            return f.measure(text)
        except Exception:
            return len(text) * 8
