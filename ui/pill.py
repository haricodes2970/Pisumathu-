"""
ui/pill.py — Floating pill overlay window.

Always-on-top, borderless, transparent-background pill.
Three states: IDLE → RECORDING → TRANSCRIBING

Design spec v2.0.3:
  IDLE        — 44×20px dark capsule, red dot left-aligned, NO glow/animation
  RECORDING   — 34px light pill, [green dot][8 bars][timer], static accent glow
  TRANSCRIBING— 30px light pill, spinner + "processing...", NO glow
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
IDLE_M  = 2     # canvas margin (px) for idle/transcribing — just clears the border
REC_M   = 32    # canvas margin for recording — accommodates 28px outer glow

# IDLE pill
IDLE_PILL_W = 44
IDLE_PILL_H = 20

# RECORDING pill
REC_PILL_H  = 34
REC_PAD_X   = 10    # left/right inner padding
DOT_D       = 6     # dot diameter (px) — both states
DOT_GAP     = 6     # gap between dot and bars
BAR_COUNT   = 8
BAR_W       = 3     # bar width (px)
BAR_GAP     = 2.5   # bar gap (px)
BAR_AREA_W  = BAR_COUNT * BAR_W + (BAR_COUNT - 1) * BAR_GAP  # 41.5px
TIMER_GAP   = 6
TIMER_W     = 40    # approximate timer text width
REC_PILL_W  = int(REC_PAD_X + DOT_D + DOT_GAP + BAR_AREA_W + TIMER_GAP + TIMER_W + REC_PAD_X)

# Bar height ranges (per spec)
BAR_MIN_H = [2, 3, 2, 3, 2, 3, 2, 3]
BAR_MAX_H = [14, 11, 15, 10, 13, 12, 14, 11]

# TRANSCRIBING pill
TRANS_PILL_H = 30
TRANS_PILL_W = 165

# Colors
RED_DOT_COLOR   = "#e11d48"
GREEN_DOT_COLOR = "#22c55e"
IDLE_BG         = "#12151e"
IDLE_BORDER     = "#1e2230"
LIGHT_BG        = "#f4f6f9"

FONT_TIMER  = ("Courier New", 9)
FONT_STATUS = ("Courier New", 9)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def _dark_shade(r: int, g: int, b: int) -> str:
    """r*0.35, g*0.35, b*0.35"""
    return f"#{round(r*0.35):02x}{round(g*0.35):02x}{round(b*0.35):02x}"


def _accent(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(r1, g1, b1, r2, g2, b2, alpha: float) -> str:
    """Blend (r1,g1,b1) over (r2,g2,b2) at alpha 0–1. Returns hex."""
    nr = round(r1 * alpha + r2 * (1 - alpha))
    ng = round(g1 * alpha + g2 * (1 - alpha))
    nb = round(b1 * alpha + b2 * (1 - alpha))
    if (nr, ng, nb) == (1, 1, 1):   # avoid chroma-key color
        nb = 2
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _over_black(r, g, b, alpha: float) -> str:
    """Accent blended over black — approximates transparent glow."""
    return _blend(r, g, b, 0, 0, 0, alpha)


def _over_light(r, g, b, alpha: float) -> str:
    """Accent blended over LIGHT_BG (#f4f6f9) — simulates bar opacity."""
    return _blend(r, g, b, 0xf4, 0xf6, 0xf9, alpha)


# ---------------------------------------------------------------------------
class PillOverlay(tk.Toplevel):
    """
    Floating pill overlay — purely visual, no user interaction.

    Receives state via set_state / set_timer / set_audio_level / update_config.
    Redraws at ~25 fps via after() on the main thread.
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
        self._spinner_angle = 0.0
        self._t             = 0.0   # elapsed seconds for bar animation

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
                level = self._audio_level
                for i in range(BAR_COUNT):
                    mn, mx = BAR_MIN_H[i], BAR_MAX_H[i]
                    if level < 0.02:
                        self._bar_heights[i]   = float(mn)
                        self._bar_opacities[i] = 0.2
                    else:
                        # Height: min_h + level * (max_h - min_h) * |sin(t*6 + i*0.8)|
                        variation = abs(math.sin(t * 6.0 + i * 0.8))
                        self._bar_heights[i] = mn + level * (mx - mn) * variation
                        # Opacity: 0.2 silent → 1.0 at full level
                        self._bar_opacities[i] = min(1.0, 0.2 + level * 0.8)

            elif state == AppState.TRANSCRIBING:
                self._spinner_angle = (t * 360.0) % 360.0

            self._t = t
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
        state   = self._state
        cfg     = self.config_ref
        r, g, b = cfg.r, cfg.g, cfg.b
        shade   = _dark_shade(r, g, b)
        accent  = _accent(r, g, b)
        c       = self._canvas
        c.delete("all")

        # ── IDLE ──────────────────────────────────────────────────────────
        if state == AppState.IDLE:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            m = IDLE_M
            cw, ch = pw + 2 * m, ph + 2 * m
            self._resize(cw, ch, ph, m)
            px, py = m, m

            # Pill body — no glow, no animation
            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)

            # Red dot: 6px, left-aligned (padding-left 7px from pill edge)
            dr = 3   # radius
            dot_x = px + 7 + dr
            dot_y = py + ph // 2
            c.create_oval(dot_x - dr, dot_y - dr,
                          dot_x + dr, dot_y + dr,
                          fill=RED_DOT_COLOR, outline="")

        # ── RECORDING ─────────────────────────────────────────────────────
        elif state == AppState.RECORDING:
            pw, ph = REC_PILL_W, REC_PILL_H
            m = REC_M
            cw, ch = pw + 2 * m, ph + 2 * m
            self._resize(cw, ch, ph, m)
            px, py = m, m

            # Static outer glow — accent@35% inner (12px), accent@15% outer (28px)
            self._glow(c, px, py, pw, ph,
                       r, g, b,
                       inner_r=12, outer_r=28,
                       inner_a=0x59 / 255,   # ~35%
                       outer_a=0x26 / 255)   # ~15%

            # Border: accent at 60% opacity over light bg
            border_col = _blend(r, g, b, 0xf4, 0xf6, 0xf9, 0.6)
            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       LIGHT_BG, border_col, 1)

            cy = py + ph // 2
            cx = px + REC_PAD_X

            # Green dot: 6px, static (no blink)
            dr = 3
            dot_x = cx + dr
            dot_y = cy
            c.create_oval(dot_x - dr, dot_y - dr,
                          dot_x + dr, dot_y + dr,
                          fill=GREEN_DOT_COLOR, outline="")

            # Waveform bars — voice-reactive
            bx = cx + DOT_D + DOT_GAP
            for i in range(BAR_COUNT):
                bh      = self._bar_heights[i]
                opacity = self._bar_opacities[i]
                bar_x   = bx + i * (BAR_W + BAR_GAP)
                top     = cy - bh / 2
                bot     = cy + bh / 2
                fc      = _over_light(r, g, b, opacity)
                c.create_rectangle(bar_x, top, bar_x + BAR_W, bot,
                                   fill=fc, outline="")

            # Timer: 9px Courier New, darkShade, right-aligned
            c.create_text(px + pw - REC_PAD_X, cy,
                          text=self._timer_text,
                          anchor="e", font=FONT_TIMER, fill=shade)

        # ── TRANSCRIBING ──────────────────────────────────────────────────
        elif state == AppState.TRANSCRIBING:
            pw, ph = TRANS_PILL_W, TRANS_PILL_H
            m = IDLE_M
            cw, ch = pw + 2 * m, ph + 2 * m
            self._resize(cw, ch, ph, m)
            px, py = m, m

            # Pill body — no glow
            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       LIGHT_BG, "#d0d4dc", 1)

            cy = py + ph // 2
            cx = px + 12

            # Spinner: 9px circle, 2px arc border
            sr = 4.5
            sa = self._spinner_angle
            c.create_arc(cx, cy - sr, cx + sr * 2, cy + sr,
                         start=sa, extent=270,
                         outline="#555555", width=2, style="arc")
            cx += round(sr * 2) + 7

            # "processing..." muted text
            c.create_text(cx, cy, text="processing...", anchor="w",
                          font=FONT_STATUS, fill="#888888")

        # ── LOADING (minimal idle pill) ────────────────────────────────────
        elif state == AppState.LOADING:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            m = IDLE_M
            cw, ch = pw + 2 * m, ph + 2 * m
            self._resize(cw, ch, ph, m)
            px, py = m, m
            self._pill(c, px, py, px + pw, py + ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)
            c.create_text(px + pw // 2, py + ph // 2,
                          text="…", anchor="center",
                          font=FONT_STATUS, fill="#4b5563")

    # ── Drawing helpers ──────────────────────────────────────────────────────

    def _resize(self, cw: int, ch: int, pill_h: int, margin: int) -> None:
        """Resize canvas/window, positioning pill 40px above taskbar."""
        self._canvas.config(width=cw, height=ch)
        x = (self._screen_w - cw) // 2
        y = self._screen_h - 40 - pill_h - margin
        self.geometry(f"{cw}x{ch}+{x}+{y}")

    def _glow(self, c,
              px: float, py: float, pw: float, ph: float,
              gr: int, gg: int, gb: int,
              inner_r: float, outer_r: float,
              inner_a: float, outer_a: float) -> None:
        """Draw concentric glow rings (farthest first) around the pill."""
        NUM = 8
        for i in range(1, NUM + 1):   # 1 = farthest, NUM = closest
            frac  = i / NUM
            dist  = outer_r + (inner_r - outer_r) * frac
            alpha = outer_a + (inner_a - outer_a) * frac
            color = _over_black(gr, gg, gb, alpha)
            ex    = dist
            r_r   = min(ph / 2 + ex, (pw + 2 * ex) / 2)
            self._pill(c,
                       px - ex, py - ex,
                       px + pw + ex, py + ph + ex,
                       r_r, color, "", 0)

    def _pill(self, c,
              x1: float, y1: float, x2: float, y2: float, r: float,
              fill: str, outline: str, width: int) -> None:
        """Draw a fully-rounded pill shape via smooth polygon."""
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
