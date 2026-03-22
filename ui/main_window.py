"""
ui/main_window.py — Main control panel window.

Dark-themed Tkinter window with:
  - Header (app name, model, GPU badge)
  - Chatbox (timestamped transcript history)
  - RGB accent-color sliders + live preview swatch
  - EN / KN language toggle
  - START / STOP button
"""

import tkinter as tk
from tkinter import ttk, font as tkfont
import datetime
from typing import Optional, Callable

from core.controller import AppState
from config.settings import AppConfig, VERSION


# ---------------------------------------------------------------------------
# Theme palette
# ---------------------------------------------------------------------------
BG = "#0d0f14"
BG2 = "#13161e"
BG3 = "#1a1e28"
TEXT_PRIMARY = "#e8eaf0"
TEXT_MUTED = "#4b5563"
TEXT_DIM = "#6b7280"
BORDER_DIM = "#1f2533"
RED = "#ef4444"

FONT_MONO = "Courier New"
FONT_KN = "Noto Sans Kannada"


# ---------------------------------------------------------------------------
# Custom gradient slider (Canvas-based, matches HTML reference spec)
# ---------------------------------------------------------------------------
class GradientSlider(tk.Canvas):
    """A horizontal slider with a gradient track (#111 → end_color) and white thumb."""

    def __init__(self, parent, variable: tk.IntVar, end_color: str,
                 command=None, **kw):
        kw.setdefault("height", 18)
        kw.setdefault("highlightthickness", 0)
        super().__init__(parent, **kw)
        self._var = variable
        self._end_color = end_color
        self._command = command
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<ButtonPress-1>", self._on_mouse)
        self.bind("<B1-Motion>", self._on_mouse)
        self.bind("<Map>", lambda e: self.after(50, self._draw))

    def _parse_hex(self, h: str):
        h = h.lstrip("#")
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2:
            return
        # Gradient track: 5px tall, vertically centered
        ty = h // 2 - 2
        r1, g1, b1 = 0x11, 0x11, 0x11
        r2, g2, b2 = self._parse_hex(self._end_color)
        n = min(w, 100)
        for i in range(n):
            t = i / max(n - 1, 1)
            r = int(r1 + (r2 - r1) * t)
            g = int(g1 + (g2 - g1) * t)
            b = int(b1 + (b2 - b1) * t)
            x1 = int(i * w / n)
            x2 = int((i + 1) * w / n) + 1
            self.create_rectangle(x1, ty, x2, ty + 5,
                                  fill=f"#{r:02x}{g:02x}{b:02x}", outline="")
        # White thumb: 14px circle
        val = self._var.get()
        x = max(7, min(w - 7, int(val / 255 * w)))
        cy = h // 2
        self.create_oval(x - 7, cy - 7, x + 7, cy + 7,
                         fill="#ffffff", outline="#0d0f14", width=2)

    def _on_mouse(self, event):
        w = self.winfo_width()
        val = max(0, min(255, int(event.x / max(w, 1) * 255)))
        self._var.set(val)
        self._draw()
        if self._command:
            self._command(val)


class MainWindow:
    """
    The primary UI surface.

    Communicates with AppController only through callbacks — never
    imports controller directly to keep presentation layer clean.
    """

    def __init__(
        self,
        root: tk.Tk,
        config: AppConfig,
        on_start: Callable,
        on_stop: Callable,
        on_color_change: Callable[[int, int, int], None],
        on_language_change: Callable[[str], None],
        on_auto_type_change: Callable[[bool], None] = None,
    ):
        self.root = root
        self.cfg = config
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_color_change = on_color_change
        self._on_language_change = on_language_change
        self._on_auto_type_change = on_auto_type_change or (lambda _: None)

        self._pill_running = False
        self._status_text = "Loading model…"

        self._build_window()
        self._build_ui()
        self._apply_accent()

    # ------------------------------------------------------------------
    # Window setup
    # ------------------------------------------------------------------

    def _build_window(self) -> None:
        self.root.title("Pisumathu")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("420x680")
        # Center on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 420) // 2
        y = (sh - 680) // 2
        self.root.geometry(f"420x680+{x}+{y}")

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self.root
        pad = dict(padx=20, pady=0)

        # ── Header ──────────────────────────────────────────────────────
        hdr = tk.Frame(root, bg=BG, height=56)
        hdr.pack(fill="x", padx=20, pady=(18, 0))

        self._lbl_title = tk.Label(
            hdr, text=f"◈ PISUMATHU  v{VERSION}",
            bg=BG, fg=self.cfg.accent_hex(),
            font=(FONT_MONO, 15, "bold"),
        )
        self._lbl_title.pack(side="left", anchor="w")

        badge_frame = tk.Frame(hdr, bg=BG)
        badge_frame.pack(side="right", anchor="e")

        self._lbl_model = tk.Label(
            badge_frame, text="model: base",
            bg=BG, fg=TEXT_DIM,
            font=(FONT_MONO, 8),
        )
        self._lbl_model.pack(side="left", padx=(0, 6))

        self._lbl_gpu = tk.Label(
            badge_frame, text="GPU",
            bg=BG3, fg=TEXT_MUTED,
            font=(FONT_MONO, 8, "bold"),
            padx=7, pady=3,
        )
        self._lbl_gpu.pack(side="left")

        # ── Divider ──────────────────────────────────────────────────────
        self._divider = tk.Frame(root, bg=BORDER_DIM, height=1)
        self._divider.pack(fill="x", padx=20, pady=(10, 0))

        # ── Chatbox ───────────────────────────────────────────────────────
        chat_outer = tk.Frame(root, bg=BG3, bd=1, relief="flat")
        chat_outer.pack(fill="both", expand=True, padx=20, pady=(14, 0))
        self._chat_border = chat_outer

        self._chat = tk.Text(
            chat_outer,
            bg=BG3, fg=TEXT_PRIMARY,
            font=(FONT_MONO, 9),
            relief="flat",
            wrap="word",
            padx=10, pady=10,
            state="disabled",
            selectbackground="#2d3447",
            insertbackground=TEXT_PRIMARY,
            height=12,
            spacing3=3,
        )
        self._chat.pack(side="left", fill="both", expand=True)

        sb = tk.Scrollbar(chat_outer, command=self._chat.yview, bg=BG3,
                          troughcolor=BG3, relief="flat", bd=0, width=8)
        sb.pack(side="right", fill="y")
        self._chat.configure(yscrollcommand=sb.set)

        # Tag for timestamp
        self._chat.tag_configure("ts", foreground=TEXT_DIM, font=(FONT_MONO, 8))
        self._chat.tag_configure("msg", foreground=TEXT_PRIMARY)

        self._append_system("Pisumathu ready. Hold both Ctrl keys to record.")

        # ── Status bar ────────────────────────────────────────────────────
        self._lbl_status = tk.Label(
            root, text="Loading model…",
            bg=BG, fg=TEXT_DIM,
            font=(FONT_MONO, 8),
            anchor="w",
        )
        self._lbl_status.pack(fill="x", padx=22, pady=(4, 0))

        # ── Divider ──────────────────────────────────────────────────────
        self._divider2 = tk.Frame(root, bg=BORDER_DIM, height=1)
        self._divider2.pack(fill="x", padx=20, pady=(10, 0))

        # ── Accent color section ──────────────────────────────────────────
        color_outer = tk.Frame(root, bg=BG)
        color_outer.pack(fill="x", padx=20, pady=(12, 0))

        tk.Label(color_outer, text="ACCENT COLOR",
                 bg=BG, fg=TEXT_MUTED,
                 font=(FONT_MONO, 7, "bold")).pack(anchor="w")

        # Styled box: bg=#161923, 1px border #1e2330, border-radius via highlight
        rgb_box = tk.Frame(
            color_outer,
            bg="#161923",
            highlightbackground="#1e2330",
            highlightthickness=1,
        )
        rgb_box.pack(fill="x", pady=(6, 0))

        # Inner padding via a child frame (14px top/bottom, 18px left/right)
        rgb_inner = tk.Frame(rgb_box, bg="#161923")
        rgb_inner.pack(fill="x", padx=18, pady=14)

        slider_area = tk.Frame(rgb_inner, bg="#161923")
        slider_area.pack(side="left", fill="x", expand=True)

        self._var_r = tk.IntVar(value=self.cfg.r)
        self._var_g = tk.IntVar(value=self.cfg.g)
        self._var_b = tk.IntVar(value=self.cfg.b)

        channels = [
            ("R", self._var_r, "#ff5555"),
            ("G", self._var_g, "#55ff88"),
            ("B", self._var_b, "#5599ff"),
        ]
        for lbl, var, end_clr in channels:
            row = tk.Frame(slider_area, bg="#161923")
            row.pack(fill="x", pady=4)
            tk.Label(row, text=lbl, bg="#161923", fg=end_clr,
                     font=(FONT_MONO, 9, "bold"), width=2).pack(side="left")
            s = GradientSlider(
                row, variable=var, end_color=end_clr,
                bg="#161923",
                command=lambda v: self._on_slider_change(),
            )
            s.pack(side="left", fill="x", expand=True, padx=(6, 0))

        # Swatch: 52x52 canvas, circle with 2px border #2a2f3d
        self._swatch = tk.Canvas(
            rgb_inner, width=52, height=52,
            bg="#161923", highlightthickness=0,
        )
        self._swatch.pack(side="right", padx=(14, 0))
        self._swatch_oval = self._swatch.create_oval(
            2, 2, 50, 50,
            fill=self.cfg.accent_hex(),
            outline="#2a2f3d",
            width=2,
        )

        # ── Language toggle ───────────────────────────────────────────────
        lang_frame = tk.Frame(root, bg=BG)
        lang_frame.pack(fill="x", padx=20, pady=(12, 0))

        tk.Label(lang_frame, text="LANGUAGE",
                 bg=BG, fg=TEXT_MUTED,
                 font=(FONT_MONO, 7, "bold")).pack(side="left")

        self._lang_var = tk.StringVar(value=self.cfg.language)
        for code, label in [("en", "EN"), ("kn", "KN")]:
            rb = tk.Radiobutton(
                lang_frame, text=label,
                variable=self._lang_var, value=code,
                bg=BG, fg=TEXT_PRIMARY,
                selectcolor=BG3,
                activebackground=BG,
                font=(FONT_MONO, 9, "bold"),
                relief="flat",
                indicatoron=False,
                padx=10, pady=4,
                command=self._on_lang_change,
                bd=1,
            )
            rb.pack(side="right", padx=(4, 0))
        self._lang_buttons = lang_frame

        # ── Type-to-cursor toggle ─────────────────────────────────────────
        type_frame = tk.Frame(root, bg=BG)
        type_frame.pack(fill="x", padx=20, pady=(10, 0))

        tk.Label(type_frame, text="OUTPUT",
                 bg=BG, fg=TEXT_MUTED,
                 font=(FONT_MONO, 7, "bold")).pack(side="left")

        self._auto_type_var = tk.BooleanVar(value=getattr(self.cfg, "auto_type", True))

        self._btn_type_cursor = tk.Checkbutton(
            type_frame,
            text="⌨  TYPE TO CURSOR",
            variable=self._auto_type_var,
            bg=BG, fg=TEXT_PRIMARY,
            selectcolor=BG3,
            activebackground=BG,
            font=(FONT_MONO, 9, "bold"),
            relief="flat",
            padx=10, pady=4,
            bd=1,
            cursor="hand2",
            command=self._on_auto_type_toggle,
        )
        self._btn_type_cursor.pack(side="right")

        self._lbl_type_hint = tk.Label(
            root,
            text="⌨ Text will be typed into whichever window you were last in",
            bg=BG, fg=TEXT_DIM,
            font=(FONT_MONO, 7),
            anchor="w",
            wraplength=380,
        )
        self._lbl_type_hint.pack(fill="x", padx=22, pady=(2, 0))
        # Show/hide hint based on toggle state
        self._update_type_hint()

        # ── Start/Stop button ─────────────────────────────────────────────
        self._btn = tk.Button(
            root,
            text="▶  START",
            font=(FONT_MONO, 11, "bold"),
            bg=self.cfg.accent_hex(),
            fg=BG,
            activebackground=self.cfg.dark_shade_hex(),
            activeforeground=BG,
            relief="flat",
            bd=0,
            padx=0, pady=14,
            cursor="hand2",
            command=self._toggle_overlay,
        )
        self._btn.pack(fill="x", padx=20, pady=(14, 20))

    # ------------------------------------------------------------------
    # Public update methods (called from AppController via UI thread)
    # ------------------------------------------------------------------

    def append_transcript(self, text: str) -> None:
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._chat.configure(state="normal")
        self._chat.insert("end", f"[{ts}] ", "ts")
        self._chat.insert("end", text + "\n\n", "msg")
        self._chat.configure(state="disabled")
        self._chat.see("end")

    def set_status(self, text: str) -> None:
        self._lbl_status.configure(text=text)
        self._status_text = text

    def set_state(self, state: AppState) -> None:
        if state == AppState.IDLE:
            self.set_status("Ready — hold both Ctrl to record.")
            self._lbl_gpu.configure(bg=BG3, fg=TEXT_MUTED)
        elif state == AppState.RECORDING:
            self.set_status("● Recording…")
            self._lbl_gpu.configure(bg="#2d1a1a", fg=RED)
        elif state == AppState.TRANSCRIBING:
            self.set_status("⟳ Transcribing…")
            self._lbl_gpu.configure(bg=BG3, fg=TEXT_MUTED)
        elif state == AppState.LOADING:
            self.set_status("Loading model…")
        elif state == AppState.ERROR:
            self.set_status("⚠ Error — check console.")

    def update_device_label(self, device: str) -> None:
        self._lbl_gpu.configure(text=device)

    def set_model_ready(self, device: str) -> None:
        self._lbl_gpu.configure(
            text=device,
            bg="#1a2a1a" if device == "CUDA" else BG3,
            fg=self.cfg.accent_hex() if device == "CUDA" else TEXT_MUTED,
        )
        self._btn.configure(state="normal")
        self.set_status("Ready — hold both Ctrl to record.")

    # ------------------------------------------------------------------
    # Internal callbacks
    # ------------------------------------------------------------------

    def _toggle_overlay(self) -> None:
        if not self._pill_running:
            self._pill_running = True
            self._btn.configure(text="■  STOP")
            self._on_start()
        else:
            self._pill_running = False
            self._btn.configure(text="▶  START")
            self._on_stop()

    def _on_slider_change(self, *_) -> None:
        r = self._var_r.get()
        g = self._var_g.get()
        b = self._var_b.get()
        self.cfg.r, self.cfg.g, self.cfg.b = r, g, b
        self._apply_accent()
        self._on_color_change(r, g, b)

    def _on_lang_change(self) -> None:
        lang = self._lang_var.get()
        self.cfg.language = lang
        self._on_language_change(lang)

    def _on_auto_type_toggle(self) -> None:
        enabled = self._auto_type_var.get()
        self._on_auto_type_change(enabled)
        self._update_type_hint()

    def _update_type_hint(self) -> None:
        if self._auto_type_var.get():
            self._lbl_type_hint.configure(
                text="⌨  Text will be typed wherever your cursor was — click a text field first",
                fg=TEXT_DIM,
            )
        else:
            self._lbl_type_hint.configure(
                text="📋  Text goes to Pisumathu chatbox only",
                fg=TEXT_MUTED,
            )

    def _apply_accent(self) -> None:
        acc = self.cfg.accent_hex()
        shade = self.cfg.dark_shade_hex()
        tint = self.cfg.light_tint_hex()

        self._lbl_title.configure(fg=acc)
        self._swatch.itemconfig(self._swatch_oval, fill=acc)
        self._divider.configure(bg=acc)
        self._divider2.configure(bg=BORDER_DIM)
        self._btn.configure(
            bg=acc,
            activebackground=shade,
            fg=BG,
        )
        # Chat border
        self._chat_border.configure(
            highlightbackground=acc,
            highlightthickness=1,
            highlightcolor=acc,
        )

    def _append_system(self, text: str) -> None:
        self._chat.configure(state="normal")
        self._chat.insert("end", text + "\n\n", "ts")
        self._chat.configure(state="disabled")
