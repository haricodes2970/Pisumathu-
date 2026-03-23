"""
ui/pill.py — Floating pill overlay window.

Always-on-top, borderless, transparent-background pill.
Three states: IDLE → RECORDING → TRANSCRIBING

Design spec v2.0.3:
  IDLE        — 40×18px dark capsule, red dot left-aligned, no glow/anim
  RECORDING   — 28px light pill, [green dot blink][8 bars][timer], no glow
  TRANSCRIBING— 26px light pill, spinner + "processing...", no glow
"""

import tkinter as tk
import math
import time
import threading

from core.controller import AppState
from config.settings import AppConfig


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
M = 2   # canvas margin (px) on each side — just enough to clear the border

# IDLE
IDLE_PILL_W = 40
IDLE_PILL_H = 18

# RECORDING
REC_PILL_H = 28
REC_PAD_X  = 8      # left/right padding inside pill
DOT_D      = 5      # dot diameter (px)
DOT_GAP    = 5      # gap between dot and bars
BAR_COUNT  = 8
BAR_W      = 2      # bar width (px)
BAR_GAP    = 2      # bar gap (px)
BAR_AREA_W = BAR_COUNT * BAR_W + (BAR_COUNT - 1) * BAR_GAP   # 30px
TIMER_GAP  = 5
TIMER_W    = 36     # approximate width of "00:00" at 8pt Courier New
REC_PILL_W = REC_PAD_X + DOT_D + DOT_GAP + BAR_AREA_W + TIMER_GAP + TIMER_W + REC_PAD_X

BAR_MIN_H = [2, 3, 2, 3, 2, 3, 2, 3]
BAR_MAX_H = [11, 8, 12, 7, 10, 9, 11, 8]

# TRANSCRIBING
TRANS_PILL_H = 26
TRANS_PILL_W = 120

# Colors
RED_DOT_COLOR   = "#e11d48"
GREEN_DOT_COLOR = "#22c55e"
IDLE_BG         = "#111318"
IDLE_BORDER     = "#1c1f2a"
LIGHT_BG        = "#f2f4f7"
LIGHT_BORDER    = "#d8dce6"
BAR_COLOR       = "#555e77"   # fixed, no accent
TIMER_COLOR     = "#777e90"   # fixed, no accent

FONT_TIMER  = ("Courier New", 8)
FONT_STATUS = ("Courier New", 8)


# ---------------------------------------------------------------------------
# Color helper — blend fg over bg at alpha, returns hex
# ---------------------------------------------------------------------------
def _blend(r1, g1, b1, r2, g2, b2, alpha: float) -> str:
    nr = round(r1 * alpha + r2 * (1 - alpha))
    ng = round(g1 * alpha + g2 * (1 - alpha))
    nb = round(b1 * alpha + b2 * (1 - alpha))
    if (nr, ng, nb) == (1, 1, 1):   # avoid chroma-key #010101
        nb = 2
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _bar_color(opacity: float) -> str:
    """#555e77 blended over #f2f4f7 at given opacity (simulates CSS opacity)."""
    return _blend(0x55, 0x5e, 0x77, 0xf2, 0xf4, 0xf7, opacity)


# ---------------------------------------------------------------------------
class PillOverlay(tk.Toplevel):
    """
    Floating pill overlay — purely visual, no user interaction.

    Updated via set_state / set_timer / set_audio_level / update_config.
    Redraws at ~25 fps on the main thread via after().
    """

    def __init__(self, master: tk.Tk, config: AppConfig):
        super().__init__(master)
        self.config_ref = config

        # Borderless, always-on-top, #010101 chroma-key transparent
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-transparentcolor", "#010101")
        self.configure(bg="#010101")
        self.title("Pisumathu")

        self._state         = AppState.IDLE
        self._timer_text    = "00:00"
        self._audio_level   = 0.0
        self._bar_heights   = [float(h) for h in BAR_MIN_H]
        self._bar_opacities = [0.2] * BAR_COUNT
        self._blink_on      = True
        self._spinner_angle = 0.0

        self._canvas = tk.Canvas(self, bg="#010101", highlightthickness=0)
        self._canvas.pack(fill="both", expand=True)

        self._screen_w = self.winfo_screenwidth()
        self._screen_h = self.winfo_screenheight()

        self._running = True
        threading.Thread(target=self._anim_loop, daemon=True).start()
        self._render()

    # ── Public API ──────────────────────────────────────────────────────────

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

    # ── Animation loop (background thread) ──────────────────────────────────

    def _anim_loop(self) -> None:
        t = 0.0
        while self._running:
            state = self._state

            if state == AppState.RECORDING:
                # Green dot: blink 1s step-end (on first 0.5s, off second 0.5s)
                self._blink_on = (t % 1.0) < 0.5

                level = self._audio_level
                for i in range(BAR_COUNT):
                    mn, mx = BAR_MIN_H[i], BAR_MAX_H[i]
                    if level < 0.02:
                        self._bar_heights[i]   = float(mn)
                        self._bar_opacities[i] = 0.2
                    else:
                        # h = min + level * |sin(t*6 + i*0.8)| * (max - min)
                        variation = abs(math.sin(t * 6.0 + i * 0.8))
                        self._bar_heights[i]   = mn + level * variation * (mx - mn)
                        self._bar_opacities[i] = min(1.0, 0.2 + level * 0.8)

            elif state == AppState.TRANSCRIBING:
                self._spinner_angle = (t * 360.0) % 360.0

            t += 0.04
            time.sleep(0.04)

    # ── Render loop (main thread via after()) ────────────────────────────────

    def _render(self) -> None:
        if not self._running:
            return
        try:
            self._draw()
        except tk.TclError:
            return
        self.after(40, self._render)   # ~25 fps

    def _draw(self) -> None:
        state = self._state
        c     = self._canvas
        c.delete("all")

        # ── IDLE ──────────────────────────────────────────────────────────
        if state == AppState.IDLE:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            cw, ch = pw + 2 * M, ph + 2 * M
            self._resize(cw, ch, ph)
            px, py = M, M

            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)

            # Red dot: 5px circle, padding-left 6px
            dr = 2.5
            dot_x = px + 6 + dr
            dot_y = py + ph / 2
            c.create_oval(dot_x - dr, dot_y - dr,
                          dot_x + dr, dot_y + dr,
                          fill=RED_DOT_COLOR, outline="")

        # ── RECORDING ─────────────────────────────────────────────────────
        elif state == AppState.RECORDING:
            pw, ph = REC_PILL_W, REC_PILL_H
            cw, ch = pw + 2 * M, ph + 2 * M
            self._resize(cw, ch, ph)
            px, py = M, M

            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       LIGHT_BG, LIGHT_BORDER, 1)

            cy = py + ph / 2
            cx = px + REC_PAD_X

            # Green dot: 5px, blink 1s step-end
            if self._blink_on:
                dr = 2.5
                dot_x = cx + dr
                c.create_oval(dot_x - dr, cy - dr,
                              dot_x + dr, cy + dr,
                              fill=GREEN_DOT_COLOR, outline="")

            # Waveform bars — voice-reactive, fixed gray color
            bx = cx + DOT_D + DOT_GAP
            for i in range(BAR_COUNT):
                bh      = self._bar_heights[i]
                opacity = self._bar_opacities[i]
                bar_x   = bx + i * (BAR_W + BAR_GAP)
                top     = cy - bh / 2
                bot     = cy + bh / 2
                c.create_rectangle(bar_x, top, bar_x + BAR_W, bot,
                                   fill=_bar_color(opacity), outline="")

            # Timer: 8px Courier New, #777e90, right-aligned
            c.create_text(px + pw - REC_PAD_X, cy,
                          text=self._timer_text,
                          anchor="e", font=FONT_TIMER, fill=TIMER_COLOR)

        # ── TRANSCRIBING ──────────────────────────────────────────────────
        elif state == AppState.TRANSCRIBING:
            pw, ph = TRANS_PILL_W, TRANS_PILL_H
            cw, ch = pw + 2 * M, ph + 2 * M
            self._resize(cw, ch, ph)
            px, py = M, M

            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       LIGHT_BG, LIGHT_BORDER, 1)

            cy = py + ph / 2
            cx = px + 10

            # Spinner: 8px circle, 1px arc border (#ccc ring, #666 top arc)
            sr = 4.0
            sa = self._spinner_angle
            # Background ring
            c.create_oval(cx, cy - sr, cx + sr * 2, cy + sr,
                          outline="#cccccc", width=1)
            # Rotating colored arc
            c.create_arc(cx, cy - sr, cx + sr * 2, cy + sr,
                         start=sa, extent=270,
                         outline="#666666", width=1, style="arc")
            cx += round(sr * 2) + 6

            # "processing..." muted
            c.create_text(cx, cy, text="processing...", anchor="w",
                          font=FONT_STATUS, fill="#888888")

        # ── LOADING (minimal idle pill) ────────────────────────────────────
        elif state == AppState.LOADING:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            cw, ch = pw + 2 * M, ph + 2 * M
            self._resize(cw, ch, ph)
            px, py = M, M
            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)

    # ── Drawing helpers ──────────────────────────────────────────────────────

    def _resize(self, cw: int, ch: int, pill_h: int) -> None:
        """Resize canvas/window, keeping pill 40px above taskbar, centered."""
        self._canvas.config(width=cw, height=ch)
        x = (self._screen_w - cw) // 2
        y = self._screen_h - 40 - pill_h - M
        self.geometry(f"{cw}x{ch}+{x}+{y}")

    def _pill(self, c,
              x1: float, y1: float, x2: float, y2: float, r: float,
              fill: str, outline: str, width: int) -> None:
        """Draw a fully-rounded pill via smooth polygon."""
        r = min(float(r), (x2 - x1) / 2, (y2 - y1) / 2)
        pts = [
            x1 + r, y1,    x2 - r, y1,
            x2,     y1,    x2,     y1 + r,
            x2,     y2 - r, x2,    y2,
            x2 - r, y2,    x1 + r, y2,
            x1,     y2,    x1,     y2 - r,
            x1,     y1 + r, x1,    y1,
        ]
        c.create_polygon(pts, smooth=True,
                         fill=fill, outline=outline, width=width)
