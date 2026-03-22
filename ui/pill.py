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
# Layout constants — matched to HTML reference spec
# ---------------------------------------------------------------------------
PILL_H = 44
PILL_PADDING_IDLE_X = 16   # padding: 7px 16px
PILL_PADDING_REC_X = 12    # padding: 7px 12px
BAR_COUNT = 8
BAR_W = 2                  # 2px wide bars
BAR_GAP = 2                # ~1.5px gap (integer canvas)
DOT_IDLE_R = 3             # 6px diameter = radius 3
DOT_REC_R = 4              # 7px diameter = radius ~3.5 → 4
GAP = 5                    # 5px gap between elements in recording

FONT_NAME_EN_DIM  = ("Courier New", 11)           # idle: not bold
FONT_NAME_EN_BOLD = ("Courier New", 11, "bold")   # recording: bold
FONT_NAME_KN_DIM  = ("Noto Sans Kannada", 11)
FONT_NAME_KN_BOLD = ("Noto Sans Kannada", 11, "bold")
FONT_TIMER  = ("Courier New", 9)                  # 9px, no bold
FONT_STATUS = ("Courier New", 9)

IDLE_W        = 170
RECORDING_W   = 310
TRANSCRIBING_W = 220

RED_DOT = "#e11d48"   # exact spec color

# ---------------------------------------------------------------------------
# Bar animation spec (from HTML reference)
# visual order: a1 a3 a5 a2 a4 a6 a7 a8
# delays per bar position (left→right):
#   pos0=a1(0s), pos1=a3(0.12s), pos2=a5(0.24s), pos3=a2(0.06s),
#   pos4=a4(0.18s), pos5=a6(0.30s), pos6=a7(0.09s), pos7=a8(0.15s)
# heights: a1=2↔14, a2=6↔10, a3=10↔3, a4=14↔4, a5=4↔14
# ---------------------------------------------------------------------------
# (min_h, max_h, delay_s) for each visual bar position 0-7
BAR_SPEC = [
    (2,  14, 0.00),   # pos0 → a1
    (10,  3, 0.12),   # pos1 → a3
    (4,  14, 0.24),   # pos2 → a5
    (6,  10, 0.06),   # pos3 → a2
    (14,  4, 0.18),   # pos4 → a4
    (2,  14, 0.30),   # pos5 → a6
    (6,  10, 0.09),   # pos6 → a7
    (10,  3, 0.15),   # pos7 → a8
]
BAR_PERIOD = 0.55   # 0.55s ease-in-out


# ---------------------------------------------------------------------------
# Color math — exact spec formula
# ---------------------------------------------------------------------------
def _light_tint(r: int, g: int, b: int) -> str:
    lr = round(r + (255 - r) * 0.88)
    lg = round(g + (255 - g) * 0.88)
    lb = round(b + (255 - b) * 0.88)
    return f"#{lr:02x}{lg:02x}{lb:02x}"

def _dark_shade(r: int, g: int, b: int) -> str:
    dr = round(r * 0.35)
    dg = round(g * 0.35)
    db = round(b * 0.35)
    return f"#{dr:02x}{dg:02x}{db:02x}"

def _accent(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


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
        self.title("Pisumathu")

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
    # Animation thread
    # ------------------------------------------------------------------

    def _anim_loop(self) -> None:
        t = 0.0
        while self._running:
            if self._state == AppState.RECORDING:
                # Per-bar ease-in-out cosine with staggered delays
                for i, (mn, mx, delay) in enumerate(BAR_SPEC):
                    t_adj = (t - delay) % BAR_PERIOD
                    frac = (1.0 - math.cos(2.0 * math.pi * t_adj / BAR_PERIOD)) / 2.0
                    self._bar_heights[i] = mn + (mx - mn) * frac
                # Blink: 1s step-end — on for first 0.5s, off for second 0.5s
                self._blink_on = (t % 1.0) < 0.5
            elif self._state == AppState.TRANSCRIBING:
                self._spinner_angle = (t * 360.0) % 360.0
            t += 0.04
            time.sleep(0.04)

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
        r, g, b = cfg.r, cfg.g, cfg.b

        tint   = _light_tint(r, g, b)
        shade  = _dark_shade(r, g, b)
        accent = _accent(r, g, b)
        lang   = cfg.language

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

        pill_r = h // 2  # full-round pill

        if state == AppState.IDLE:
            # Border: 1px darkShade
            self._draw_pill(c, 0, 0, w, h, pill_r, fill=tint, outline=shade, width=1)
            cx = PILL_PADDING_IDLE_X
            cy = h // 2
            # 6px dot, darkShade color
            c.create_oval(cx, cy - DOT_IDLE_R, cx + DOT_IDLE_R * 2, cy + DOT_IDLE_R,
                          fill=shade, outline="")
            cx += DOT_IDLE_R * 2 + GAP + 1
            name = "ಪಿಸುಮಾಥು" if lang == "kn" else "PISUMATHU"
            font = FONT_NAME_KN_DIM if lang == "kn" else FONT_NAME_EN_DIM
            c.create_text(cx, cy, text=name, anchor="w", font=font, fill=shade)

        elif state == AppState.RECORDING:
            # Border: 2px accent (≈1.5px)
            self._draw_pill(c, 0, 0, w, h, pill_r, fill=tint, outline=accent, width=2)
            cx = PILL_PADDING_REC_X
            cy = h // 2
            # Red blinking dot: 7px → radius 3.5, use 4
            dot_color = RED_DOT if self._blink_on else tint
            c.create_oval(cx, cy - DOT_REC_R, cx + DOT_REC_R * 2, cy + DOT_REC_R,
                          fill=dot_color, outline="")
            cx += DOT_REC_R * 2 + GAP

            # Waveform bars: 2px wide, ~1.5px gap
            bar_area_h = 16
            for i, bh in enumerate(self._bar_heights):
                bx = cx + i * (BAR_W + BAR_GAP)
                by_top = cy - bh / 2
                by_bot = cy + bh / 2
                c.create_rectangle(bx, by_top, bx + BAR_W, by_bot,
                                   fill=accent, outline="")
            cx += BAR_COUNT * (BAR_W + BAR_GAP) + GAP

            # Name bold, darkShade
            name = "ಪಿಸುಮಾಥು" if lang == "kn" else "PISUMATHU"
            font = FONT_NAME_KN_BOLD if lang == "kn" else FONT_NAME_EN_BOLD
            c.create_text(cx, cy, text=name, anchor="w", font=font, fill=shade)
            name_w = self._text_width(name, font)
            cx += name_w + GAP

            # Timer: 9px, darkShade
            c.create_text(w - PILL_PADDING_REC_X, cy, text=self._timer_text,
                          anchor="e", font=FONT_TIMER, fill=shade)

        elif state == AppState.TRANSCRIBING:
            self._draw_pill(c, 0, 0, w, h, pill_r, fill=tint, outline=accent, width=1)
            cx = PILL_PADDING_REC_X
            cy = h // 2
            sa = self._spinner_angle
            sr = 8
            c.create_arc(cx - sr, cy - sr, cx + sr, cy + sr,
                         start=sa, extent=270, outline=accent,
                         width=2, style="arc")
            cx += sr * 2 + GAP
            c.create_text(cx, cy, text="processing...", anchor="w",
                          font=FONT_STATUS, fill=shade)

        elif state == AppState.LOADING:
            self._draw_pill(c, 0, 0, w, h, pill_r, fill=tint, outline=shade, width=1)
            cy = h // 2
            c.create_text(w // 2, cy, text="loading model…",
                          anchor="center", font=FONT_STATUS, fill=shade)

    def _draw_pill(self, c, x1, y1, x2, y2, r, fill, outline, width):
        """Draw a fully-rounded pill shape on canvas."""
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2,     y1,
            x2,     y1 + r,
            x2,     y2 - r,
            x2,     y2,
            x2 - r, y2,
            x1 + r, y2,
            x1,     y2,
            x1,     y2 - r,
            x1,     y1 + r,
            x1,     y1,
        ]
        c.create_polygon(pts, smooth=True, fill=fill, outline=outline, width=width)

    def _position_pill(self, w: int) -> None:
        x = (self._screen_w - w) // 2
        y = self._screen_h - PILL_H - 40  # 40px above taskbar
        self.geometry(f"{w}x{PILL_H}+{x}+{y}")

    def _text_width(self, text: str, font) -> int:
        try:
            f = tk.font.Font(font=font)
            return f.measure(text)
        except Exception:
            return len(text) * 8
