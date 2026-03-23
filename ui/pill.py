"""
ui/pill.py — Floating pill overlay window.

Always-on-top, borderless, transparent-background pill.
Three states: IDLE → RECORDING → TRANSCRIBING

Design spec v2.0.3:
  IDLE        — 52×24px dark capsule, green dot only, breathing glow
  RECORDING   — 40px light pill, [red dot][8 bars][timer], accent glow
  TRANSCRIBING— 36px light pill, spinner + "processing..."
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
GLOW_M = 36          # glow margin (px) on each side around pill

# Pill dimensions
IDLE_PILL_W  = 52
IDLE_PILL_H  = 24
REC_PILL_H   = 40
TRANS_PILL_H = 36
TRANS_PILL_W = 170

# Recording pill layout
REC_PAD_X  = 14     # left/right padding
DOT_D      = 8      # red dot diameter
DOT_GAP    = 8      # gap between dot and bars
BAR_COUNT  = 8
BAR_W      = 4      # bar width px
BAR_GAP    = 3      # gap between bars px
BAR_AREA_W = BAR_COUNT * BAR_W + (BAR_COUNT - 1) * BAR_GAP  # 53px
TIMER_GAP  = 8
TIMER_W    = 42     # approximate timer text width
REC_PILL_W = REC_PAD_X + DOT_D + DOT_GAP + BAR_AREA_W + TIMER_GAP + TIMER_W + REC_PAD_X

# Bar height ranges (per spec)
BAR_MIN_H = [2, 3, 2, 4, 2, 3, 2, 3]
BAR_MAX_H = [18, 14, 17, 12, 18, 15, 17, 13]

# Colors
RED_DOT_COLOR   = "#e11d48"
GREEN_DOT_COLOR = "#22c55e"
IDLE_BG         = "#1a1d28"
IDLE_BORDER     = "#252a3a"
LIGHT_BG        = "#f0f4f8"

FONT_TIMER  = ("Courier New", 9)
FONT_STATUS = ("Courier New", 9)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------
def _dark_shade(r: int, g: int, b: int) -> str:
    """darkShade = r*0.35, g*0.35, b*0.35"""
    return f"#{round(r*0.35):02x}{round(g*0.35):02x}{round(b*0.35):02x}"


def _accent(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _blend(r1, g1, b1, r2, g2, b2, alpha: float) -> str:
    """Blend (r1,g1,b1) over (r2,g2,b2) at alpha 0-1. Returns hex string."""
    nr = round(r1 * alpha + r2 * (1 - alpha))
    ng = round(g1 * alpha + g2 * (1 - alpha))
    nb = round(b1 * alpha + b2 * (1 - alpha))
    if (nr, ng, nb) == (1, 1, 1):   # avoid chroma-key #010101
        nb = 2
    return f"#{nr:02x}{ng:02x}{nb:02x}"


def _over_black(r, g, b, alpha: float) -> str:
    """Blend glow color over black (transparent bg approximation)."""
    return _blend(r, g, b, 0, 0, 0, alpha)


def _over_light(r, g, b, alpha: float) -> str:
    """Blend accent over LIGHT_BG (#f0f4f8)."""
    return _blend(r, g, b, 0xf0, 0xf4, 0xf8, alpha)


# ---------------------------------------------------------------------------
class PillOverlay(tk.Toplevel):
    """
    Floating pill overlay — purely visual, no user interaction.

    Receives updates via public methods (set_state, set_timer,
    set_audio_level, update_config) and redraws at ~25 fps.
    """

    def __init__(self, master: tk.Tk, config: AppConfig):
        super().__init__(master)
        self.config_ref = config

        # Window chrome: borderless, always-on-top, #010101 chroma-key transparent
        self.overrideredirect(True)
        self.wm_attributes("-topmost", True)
        self.wm_attributes("-transparentcolor", "#010101")
        self.configure(bg="#010101")
        self.title("Pisumathu")

        # Animation state
        self._state        = AppState.IDLE
        self._timer_text   = "00:00"
        self._audio_level  = 0.0
        self._bar_heights  = [float(h) for h in BAR_MIN_H]
        self._spinner_angle = 0.0
        self._blink_on     = True
        self._glow_phase   = 0.0    # 0.0–1.0 breathing progress

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

            if state == AppState.IDLE:
                # Outer glow breathing: 2s ease-in-out
                self._glow_phase = (1.0 - math.cos(2 * math.pi * t / 2.0)) / 2.0

            elif state == AppState.RECORDING:
                # Outer glow breathing: 1.5s ease-in-out
                self._glow_phase = (1.0 - math.cos(2 * math.pi * t / 1.5)) / 2.0
                # Red dot blink: 1s step-end
                self._blink_on = (t % 1.0) < 0.5
                # Voice-reactive bars driven by RMS level
                level = self._audio_level
                for i in range(BAR_COUNT):
                    mn, mx = BAR_MIN_H[i], BAR_MAX_H[i]
                    if level < 0.02:
                        self._bar_heights[i] = float(mn)
                    else:
                        # Oscillate per bar with phase offset; normalize to 0-1
                        s = (math.sin(t * 6.0 + i * 0.8) + 1.0) / 2.0
                        self._bar_heights[i] = mn + level * (mx - mn) * s

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
        state    = self._state
        cfg      = self.config_ref
        r, g, b  = cfg.r, cfg.g, cfg.b
        shade    = _dark_shade(r, g, b)
        accent   = _accent(r, g, b)
        c        = self._canvas
        c.delete("all")

        # ── IDLE ──────────────────────────────────────────────────────────
        if state == AppState.IDLE:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            cw = pw + 2 * GLOW_M
            ch = ph + 2 * GLOW_M
            self._resize(cw, ch, ph)
            px, py = GLOW_M, GLOW_M
            gp = self._glow_phase

            # Green breathing glow: OFF 0 0 8px #22c55e22 / 0 0 16px #22c55e11
            #                        ON 0 0 14px #22c55e55 / 0 0 28px #22c55e22
            inner_a = (0x22 + gp * (0x55 - 0x22)) / 255   # 0.133 → 0.333
            outer_a = (0x11 + gp * (0x22 - 0x11)) / 255   # 0.067 → 0.133
            inner_r = 8  + gp * 6    # 8 → 14 px
            outer_r = 16 + gp * 12   # 16 → 28 px
            self._glow(c, px, py, pw, ph,
                       0x22, 0xc5, 0x5e,
                       inner_r, outer_r, inner_a, outer_a)

            # Pill body: dark, 1px border
            self._pill(c, px, py, px+pw, py+ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)

            # Green dot — 9px circle centered in pill, with pulse glow
            dr = 4.5
            cx = px + pw // 2
            cy = py + ph // 2
            # Dot glow (blended green over pill bg)
            dot_glow_r = dr + 2 + gp * 2
            dot_glow_c = _blend(0x22, 0xc5, 0x5e, 0x1a, 0x1d, 0x28, 0.30 + gp * 0.25)
            c.create_oval(cx - dot_glow_r, cy - dot_glow_r,
                          cx + dot_glow_r, cy + dot_glow_r,
                          fill=dot_glow_c, outline="")
            # Main dot
            c.create_oval(cx - dr, cy - dr, cx + dr, cy + dr,
                          fill=GREEN_DOT_COLOR, outline="")

        # ── RECORDING ─────────────────────────────────────────────────────
        elif state == AppState.RECORDING:
            pw, ph = REC_PILL_W, REC_PILL_H
            cw = pw + 2 * GLOW_M
            ch = ph + 2 * GLOW_M
            self._resize(cw, ch, ph)
            px, py = GLOW_M, GLOW_M
            gp = self._glow_phase

            # Accent breathing glow: OFF 0 0 14px accent@44 / 0 0 28px accent@1a
            #                         ON 0 0 22px accent@77 / 0 0 44px accent@33
            inner_a = (0x44 + gp * (0x77 - 0x44)) / 255   # 0.267 → 0.467
            outer_a = (0x1a + gp * (0x33 - 0x1a)) / 255   # 0.102 → 0.200
            inner_r = 14 + gp * 8    # 14 → 22 px
            outer_r = 28 + gp * 16   # 28 → 44 px
            self._glow(c, px, py, pw, ph,
                       r, g, b,
                       inner_r, outer_r, inner_a, outer_a)

            # Pill body: light bg, 1.5px accent border (width=2 approximates 1.5)
            self._pill(c, px, py, px+pw, py+ph, ph // 2,
                       LIGHT_BG, accent, 2)

            cy = py + ph // 2
            cx = px + REC_PAD_X

            # Red dot 8px, blink 1s step-end
            dot_col = RED_DOT_COLOR if self._blink_on else LIGHT_BG
            c.create_oval(cx, cy - DOT_D // 2,
                          cx + DOT_D, cy + DOT_D // 2,
                          fill=dot_col, outline="")

            # Waveform bars — voice-reactive via RMS
            bx    = cx + DOT_D + DOT_GAP
            level = self._audio_level
            for i in range(BAR_COUNT):
                bh    = self._bar_heights[i]
                bar_x = bx + i * (BAR_W + BAR_GAP)
                top   = cy - bh / 2
                bot   = cy + bh / 2

                if level < 0.02:
                    # Silent: flat at min height, dimmed to 25% opacity over bg
                    fc = _over_light(r, g, b, 0.25)
                else:
                    # Glow halo behind bar (intensifies with level)
                    ga = min(0.15 + level * 0.30, 0.50)
                    gc = _over_light(r, g, b, ga)
                    c.create_rectangle(bar_x - 2, top - 2,
                                       bar_x + BAR_W + 2, bot + 2,
                                       fill=gc, outline="")
                    fc = accent

                c.create_rectangle(bar_x, top, bar_x + BAR_W, bot,
                                   fill=fc, outline="")

            # Timer — 9px Courier New, darkShade, right-aligned
            c.create_text(px + pw - REC_PAD_X, cy,
                          text=self._timer_text,
                          anchor="e", font=FONT_TIMER, fill=shade)

        # ── TRANSCRIBING ──────────────────────────────────────────────────
        elif state == AppState.TRANSCRIBING:
            pw, ph = TRANS_PILL_W, TRANS_PILL_H
            cw = pw + 2 * GLOW_M
            ch = ph + 2 * GLOW_M
            self._resize(cw, ch, ph)
            px, py = GLOW_M, GLOW_M

            # Subtle gray outer glow
            self._glow(c, px, py, pw, ph,
                       0x99, 0x99, 0x99, 8, 16, 0.07, 0.04)

            # Pill body
            self._pill(c, px, py, px+pw, py+ph, ph // 2,
                       LIGHT_BG, "#cccccc", 1)

            cy = py + ph // 2
            cx = px + 14

            # Spinner: 11px circle, 2px border, rotating arc top = #444
            sr = 5.5
            sa = self._spinner_angle
            c.create_arc(cx, cy - sr, cx + sr * 2, cy + sr,
                         start=sa, extent=270,
                         outline="#444444", width=2, style="arc")
            cx += round(sr * 2) + 8

            # "processing..." muted gray text
            c.create_text(cx, cy, text="processing...", anchor="w",
                          font=FONT_STATUS, fill="#888888")

        # ── LOADING (show minimal idle pill) ──────────────────────────────
        elif state == AppState.LOADING:
            pw, ph = IDLE_PILL_W, IDLE_PILL_H
            cw = pw + 2 * GLOW_M
            ch = ph + 2 * GLOW_M
            self._resize(cw, ch, ph)
            px, py = GLOW_M, GLOW_M
            self._pill(c, px, py, px+pw, py+ph, ph // 2,
                       IDLE_BG, IDLE_BORDER, 1)
            c.create_text(px + pw // 2, py + ph // 2,
                          text="…", anchor="center",
                          font=FONT_STATUS, fill="#4b5563")

    # ── Drawing helpers ──────────────────────────────────────────────────────

    def _resize(self, cw: int, ch: int, pill_h: int) -> None:
        """Resize canvas/window and reposition so pill sits 40px above taskbar."""
        self._canvas.config(width=cw, height=ch)
        x = (self._screen_w - cw) // 2
        y = self._screen_h - 40 - pill_h - GLOW_M
        self.geometry(f"{cw}x{ch}+{x}+{y}")

    def _glow(self, c,
              px: float, py: float, pw: float, ph: float,
              gr: int, gg: int, gb: int,
              inner_r: float, outer_r: float,
              inner_a: float, outer_a: float) -> None:
        """
        Draw 8 concentric glow rings around the pill (farthest first).
        Colors are blended over black (chroma-key transparent bg approximation).
        """
        NUM = 8
        for i in range(1, NUM + 1):     # 1 = farthest ring, NUM = closest ring
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
