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
from config.settings import AppConfig


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
        self.root.geometry("420x620")
        # Center on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 420) // 2
        y = (sh - 620) // 2
        self.root.geometry(f"420x620+{x}+{y}")

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
            hdr, text="◈ PISUMATHU",
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
        color_frame = tk.Frame(root, bg=BG)
        color_frame.pack(fill="x", padx=20, pady=(12, 0))

        tk.Label(color_frame, text="ACCENT COLOR",
                 bg=BG, fg=TEXT_MUTED,
                 font=(FONT_MONO, 7, "bold")).pack(anchor="w")

        sliders_row = tk.Frame(color_frame, bg=BG)
        sliders_row.pack(fill="x", pady=(6, 0))

        slider_area = tk.Frame(sliders_row, bg=BG)
        slider_area.pack(side="left", fill="x", expand=True)

        self._var_r = tk.IntVar(value=self.cfg.r)
        self._var_g = tk.IntVar(value=self.cfg.g)
        self._var_b = tk.IntVar(value=self.cfg.b)

        channels = [
            ("R", self._var_r, "#ff5555"),
            ("G", self._var_g, "#55ff88"),
            ("B", self._var_b, "#5599ff"),
        ]
        for lbl, var, clr in channels:
            row = tk.Frame(slider_area, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=lbl, bg=BG, fg=clr,
                     font=(FONT_MONO, 9, "bold"), width=2).pack(side="left")
            s = tk.Scale(
                row, from_=0, to=255, orient="horizontal",
                variable=var, bg=BG, fg=TEXT_PRIMARY,
                troughcolor=BG3, highlightthickness=0,
                relief="flat", sliderrelief="flat",
                sliderlength=14, width=8,
                showvalue=False,
                command=lambda _=None: self._on_slider_change(),
            )
            s.pack(side="left", fill="x", expand=True)

        # Swatch
        self._swatch = tk.Canvas(
            sliders_row, width=48, height=48,
            bg=BG, highlightthickness=0,
        )
        self._swatch.pack(side="right", padx=(12, 0))
        self._swatch_oval = self._swatch.create_oval(
            4, 4, 44, 44,
            fill=self.cfg.accent_hex(), outline="",
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
