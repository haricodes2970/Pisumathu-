import tkinter as tk
from tkinter import scrolledtext, ttk
import threading
import tempfile
import os
import wave
import pyaudio
import whisper
import torch
import time
import json

# ── Config ───────────────────────────────────────────────────────────────────
MODEL_SIZE   = "small"
SAMPLE_RATE  = 16000
CHANNELS     = 1
CHUNK        = 1024
FORMAT       = pyaudio.paInt16
DEVICE       = "cuda" if torch.cuda.is_available() else "cpu"
CONFIG_FILE  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ── Language options ──────────────────────────────────────────────────────────
LANGUAGES = [
    ("Auto Detect", None),
    ("English",     "en"),
    ("Kannada",     "kn"),
    ("Hindi",       "hi"),
    ("Telugu",      "te"),
    ("Japanese",    "ja"),
]
LANG_DISPLAY = [name for name, _ in LANGUAGES]
LANG_CODE    = {name: code for name, code in LANGUAGES}
INDIC_LANGS  = {"kn", "hi", "te"}
MODEL_SIZES  = ["tiny", "base", "small", "medium", "large"]

# ── Colours & fonts ───────────────────────────────────────────────────────────
BG          = "#0d0f14"
SURFACE     = "#161923"
ACCENT      = "#00e5ff"
ACCENT_DIM  = "#007a8a"
TEXT        = "#e8eaf0"
TEXT_DIM    = "#5a6070"
DANGER      = "#ff4f5e"
WARN        = "#ffb300"
FONT_TITLE  = ("Courier New", 13, "bold")
FONT_CHAT   = ("Courier New", 11)
FONT_BTN    = ("Courier New", 12, "bold")
FONT_STATUS = ("Courier New", 9)

DEFAULT_RGB = (0, 229, 255)
DIM_FACTOR  = 0.43


def _rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def _make_dim(r, g, b):
    return _rgb_to_hex(r * DIM_FACTOR, g * DIM_FACTOR, b * DIM_FACTOR)


class PisumathuApp:
    def __init__(self, root: tk.Tk):
        self.root          = root
        self.root.title("Pisumathu")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("540x870")

        self.recording     = False
        self.frames        = []
        self.audio         = pyaudio.PyAudio()
        self.stream        = None
        self.model         = None
        self.model_size    = MODEL_SIZE
        self.model_loading = False

        # ── Accent color state (live) ─────────────────────────────────────────
        self._ar, self._ag, self._ab = DEFAULT_RGB
        self._accent     = _rgb_to_hex(*DEFAULT_RGB)
        self._accent_dim = _make_dim(*DEFAULT_RGB)

        # ── Pill overlay reference (set externally when pill is open) ─────────
        self.pill_overlay = None

        # ── Pill language toggle (True = English, False = Kannada) ────────────
        self._pill_en = True

        self._load_config()
        self._build_ui()
        self._load_model(MODEL_SIZE)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r") as f:
                cfg = json.load(f)
            rgb = cfg.get("accent_rgb", list(DEFAULT_RGB))
            self._ar, self._ag, self._ab = int(rgb[0]), int(rgb[1]), int(rgb[2])
            self._accent     = _rgb_to_hex(self._ar, self._ag, self._ab)
            self._accent_dim = _make_dim(self._ar, self._ag, self._ab)
            self._pill_en    = cfg.get("pill_lang_en", True)
        except Exception:
            pass

    def _save_config(self):
        try:
            cfg = {
                "accent_rgb":   [self._ar, self._ag, self._ab],
                "pill_lang_en": self._pill_en,
            }
            with open(CONFIG_FILE, "w") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    # ── Model loading ─────────────────────────────────────────────────────────

    def _load_model(self, size: str):
        self.model_loading = True
        self._set_btn_locked(True)
        self._set_status(f"● LOADING {size} …", WARN)
        self._append_system(f"Loading model '{size}' on {DEVICE} …")
        threading.Thread(target=self._load_model_thread, args=(size,), daemon=True).start()

    def _load_model_thread(self, size: str):
        try:
            m = whisper.load_model(size, device=DEVICE)
            self.root.after(0, self._on_model_loaded, size, m)
        except Exception as e:
            self.root.after(0, self._on_model_error, str(e))

    def _on_model_loaded(self, size: str, m):
        self.model         = m
        self.model_size    = size
        self.model_loading = False
        self.model_lbl.config(text=f"model: {size}")
        self._append_system(f"Model '{size}' ready.")
        self._set_btn_locked(False)
        self._set_status("● READY", TEXT_DIM)
        self._check_lang_warning()

    def _on_model_error(self, err: str):
        self.model_loading = False
        self._append_error(f"Failed to load model: {err}")
        self._set_btn_locked(False)
        self._set_status("● ERROR", DANGER)

    def _on_model_change(self, event=None):
        new_size = self.model_var.get()
        if new_size == self.model_size and self.model is not None:
            return
        self._load_model(new_size)

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ttk dark style (shared by both comboboxes)
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=BG, background=BG,
            foreground=self._accent,
            selectbackground=self._accent_dim,
            selectforeground=BG,
            bordercolor=self._accent_dim,
            arrowcolor=self._accent, padding=3,
        )
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", BG)],
                  foreground=[("readonly", self._accent)])

        # Header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        self.hdr_title = tk.Label(hdr, text="◈ PISUMATHU", font=FONT_TITLE,
                                  bg=BG, fg=self._accent)
        self.hdr_title.pack(side="left")

        self.gpu_badge = tk.Label(
            hdr,
            text="  GPU  " if DEVICE == "cuda" else "  CPU  ",
            font=("Courier New", 8, "bold"),
            bg=self._accent if DEVICE == "cuda" else TEXT_DIM,
            fg=BG, padx=6, pady=2
        )
        self.gpu_badge.pack(side="right")

        self.model_lbl = tk.Label(hdr, text=f"model: {MODEL_SIZE}",
                                  font=FONT_STATUS, bg=BG, fg=TEXT_DIM)
        self.model_lbl.pack(side="right", padx=10)

        # Controls row: lang + model selectors
        ctrl_row = tk.Frame(self.root, bg=BG)
        ctrl_row.pack(fill="x", padx=24, pady=(8, 0))

        tk.Label(ctrl_row, text="lang:", font=FONT_STATUS,
                 bg=BG, fg=TEXT_DIM).pack(side="left")

        self.lang_var = tk.StringVar(value="Auto Detect")
        self.lang_combo = ttk.Combobox(
            ctrl_row, textvariable=self.lang_var, values=LANG_DISPLAY,
            state="readonly", width=13, style="Dark.TCombobox", font=FONT_STATUS,
        )
        self.lang_combo.pack(side="left", padx=(6, 0))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_change)

        tk.Label(ctrl_row, text="  model:", font=FONT_STATUS,
                 bg=BG, fg=TEXT_DIM).pack(side="left")

        self.model_var = tk.StringVar(value=MODEL_SIZE)
        self.model_combo = ttk.Combobox(
            ctrl_row, textvariable=self.model_var, values=MODEL_SIZES,
            state="readonly", width=8, style="Dark.TCombobox", font=FONT_STATUS,
        )
        self.model_combo.pack(side="left", padx=(6, 0))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        # Warning label
        self.warn_lbl = tk.Label(self.root, text="",
                                 font=("Courier New", 8), bg=BG, fg=WARN)
        self.warn_lbl.pack(fill="x", padx=24)

        # Divider
        self.divider = tk.Frame(self.root, bg=self._accent_dim, height=1)
        self.divider.pack(fill="x", padx=24, pady=(6, 0))

        # Chat box
        self.chat_frame = tk.Frame(self.root, bg=SURFACE,
                                   highlightbackground=self._accent_dim,
                                   highlightthickness=1)
        self.chat_frame.pack(fill="both", expand=True, padx=24, pady=16)

        self.chat = scrolledtext.ScrolledText(
            self.chat_frame, font=FONT_CHAT,
            bg=SURFACE, fg=TEXT, insertbackground=self._accent,
            relief="flat", wrap="word", padx=14, pady=12,
            state="disabled", cursor="arrow"
        )
        self.chat.pack(fill="both", expand=True)

        self.chat.tag_config("you",     foreground=self._accent, font=("Courier New", 9, "bold"))
        self.chat.tag_config("msg",     foreground=TEXT,         font=FONT_CHAT)
        self.chat.tag_config("ts",      foreground=TEXT_DIM,     font=("Courier New", 8))
        self.chat.tag_config("whisper", foreground=TEXT_DIM,     font=("Courier New", 9, "italic"))
        self.chat.tag_config("error",   foreground=DANGER,       font=("Courier New", 9, "italic"))

        self._append_system("Hold the button below to talk. Release to transcribe.")

        # Status bar
        self.status_var = tk.StringVar(value="● READY")
        self.status_lbl = tk.Label(self.root, textvariable=self.status_var,
                                   font=FONT_STATUS, bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(pady=(0, 6))

        # Waveform canvas
        self.wave_canvas = tk.Canvas(self.root, bg=BG, height=40, width=492,
                                     highlightthickness=0)
        self.wave_canvas.pack(padx=24)
        self._wave_bars = []
        for i in range(30):
            x = 8 + i * 16
            bar = self.wave_canvas.create_rectangle(
                x, 20, x + 8, 20, fill=self._accent_dim, outline=""
            )
            self._wave_bars.append(bar)
        self._wave_anim_running = False

        # ── Color section (RGB sliders + EN/KN toggle) ─────────────────────
        self._build_color_section()

        # Push-to-talk button
        self.btn = tk.Label(
            self.root, text="⏺  HOLD TO TALK", font=FONT_BTN,
            bg=self._accent, fg=BG, padx=0, pady=18,
            cursor="hand2", width=30
        )
        self.btn.pack(padx=24, pady=(10, 22), fill="x")
        self.btn.bind("<ButtonPress-1>",   self._on_press)
        self.btn.bind("<ButtonRelease-1>", self._on_release)

        self.root.bind("<KeyPress-space>",   self._on_press)
        self.root.bind("<KeyRelease-space>", self._on_release)

        tk.Label(self.root, text="or hold  SPACE",
                 font=FONT_STATUS, bg=BG, fg=TEXT_DIM).pack(pady=(0, 12))

    def _build_color_section(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="x", padx=24, pady=(8, 0))

        # Left: RGB sliders
        sliders_frame = tk.Frame(outer, bg=BG)
        sliders_frame.pack(side="left", fill="x", expand=True)

        self._r_var = tk.IntVar(value=self._ar)
        self._g_var = tk.IntVar(value=self._ag)
        self._b_var = tk.IntVar(value=self._ab)

        for label, var, attr in [("R", self._r_var, "_ar"),
                                  ("G", self._g_var, "_ag"),
                                  ("B", self._b_var, "_ab")]:
            row = tk.Frame(sliders_frame, bg=BG)
            row.pack(fill="x", pady=1)
            tk.Label(row, text=label, font=FONT_STATUS, bg=BG,
                     fg=TEXT_DIM, width=2).pack(side="left")
            sl = tk.Scale(
                row, variable=var, from_=0, to=255,
                orient="horizontal", length=260, showvalue=False,
                bg=BG, fg=self._accent,
                troughcolor=SURFACE, highlightthickness=0,
                activebackground=self._accent, bd=0,
                command=lambda _v, _a=attr, _var=var: self._on_rgb_change(_a, _var),
            )
            sl.pack(side="left", padx=(4, 0))

        # Right: swatch + toggle
        right = tk.Frame(outer, bg=BG)
        right.pack(side="left", padx=(10, 0))

        self.swatch = tk.Label(right, bg=self._accent,
                               width=3, relief="flat", pady=6)
        self.swatch.pack(pady=(2, 4))

        self.hex_lbl = tk.Label(right, text=self._accent,
                                font=("Courier New", 7), bg=BG, fg=TEXT_DIM)
        self.hex_lbl.pack()

        # EN / KN toggle button
        self.pill_lang_btn = tk.Label(
            right,
            text="EN" if self._pill_en else "KN",
            font=("Courier New", 8, "bold"),
            bg=self._accent_dim, fg=TEXT,
            padx=6, pady=3, cursor="hand2"
        )
        self.pill_lang_btn.pack(pady=(6, 0))
        self.pill_lang_btn.bind("<Button-1>", self._toggle_pill_lang)

    # ── Accent color logic ────────────────────────────────────────────────────

    def _on_rgb_change(self, attr, var):
        setattr(self, attr, var.get())
        self._accent     = _rgb_to_hex(self._ar, self._ag, self._ab)
        self._accent_dim = _make_dim(self._ar, self._ag, self._ab)
        self._apply_accent()
        self._save_config()

    def _apply_accent(self):
        ac  = self._accent
        dim = self._accent_dim

        # Header title
        self.hdr_title.config(fg=ac)

        # GPU badge (only when CUDA, otherwise stays TEXT_DIM)
        if DEVICE == "cuda":
            self.gpu_badge.config(bg=ac)

        # Divider line
        self.divider.config(bg=dim)

        # Chat box border
        self.chat_frame.config(highlightbackground=dim)

        # Chat "you" tag
        self.chat.tag_config("you", foreground=ac)

        # Waveform bars (idle color)
        for bar in self._wave_bars:
            self.wave_canvas.itemconfig(bar, fill=dim)

        # Hold-to-talk button (only when in READY state)
        current_bg = self.btn.cget("bg")
        if current_bg not in (DANGER, TEXT_DIM, "#5a6070"):
            # Not recording / loading — safe to update
            if current_bg != DANGER:
                self.btn.config(bg=ac)

        # Swatch + hex label
        self.swatch.config(bg=ac)
        self.hex_lbl.config(text=ac)

        # Toggle button dim background
        self.pill_lang_btn.config(bg=dim)

        # Pill overlay (if open)
        if self.pill_overlay is not None:
            try:
                self.pill_overlay.update_accent(ac, dim)
            except Exception:
                self.pill_overlay = None

    # ── EN / KN toggle ────────────────────────────────────────────────────────

    def _toggle_pill_lang(self, event=None):
        self._pill_en = not self._pill_en
        label = "EN" if self._pill_en else "KN"
        self.pill_lang_btn.config(text=label)
        if self.pill_overlay is not None:
            try:
                self.pill_overlay.update_pill_lang(self._pill_en)
            except Exception:
                self.pill_overlay = None
        self._save_config()

    # ── Warning helper ────────────────────────────────────────────────────────

    def _on_lang_change(self, event=None):
        self._check_lang_warning()

    def _check_lang_warning(self):
        lang_code = LANG_CODE.get(self.lang_var.get())
        if lang_code in INDIC_LANGS and self.model_size in ("tiny", "base"):
            self.warn_lbl.config(
                text=f"⚠  '{self.lang_var.get()}' needs small/medium/large for accurate results"
            )
        else:
            self.warn_lbl.config(text="")

    # ── Button lock (while model loads) ──────────────────────────────────────

    def _set_btn_locked(self, locked: bool):
        if locked:
            self.btn.config(bg=TEXT_DIM, text="⏳  LOADING MODEL …", cursor="watch")
            self.btn.unbind("<ButtonPress-1>")
            self.btn.unbind("<ButtonRelease-1>")
            self.root.unbind("<KeyPress-space>")
            self.root.unbind("<KeyRelease-space>")
        else:
            self.btn.config(bg=self._accent, text="⏺  HOLD TO TALK", cursor="hand2")
            self.btn.bind("<ButtonPress-1>",   self._on_press)
            self.btn.bind("<ButtonRelease-1>", self._on_release)
            self.root.bind("<KeyPress-space>",   self._on_press)
            self.root.bind("<KeyRelease-space>", self._on_release)

    # ── Recording ─────────────────────────────────────────────────────────────

    def _on_press(self, event=None):
        if self.recording or self.model is None:
            return
        self.recording = True
        self.frames    = []
        self.btn.config(bg=DANGER, text="⏹  RECORDING …  release to transcribe")
        self._set_status("● RECORDING", DANGER)
        self._start_wave_anim()

        self.stream = self.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK
        )
        threading.Thread(target=self._record_loop, daemon=True).start()

    def _record_loop(self):
        while self.recording:
            try:
                data = self.stream.read(CHUNK, exception_on_overflow=False)
                self.frames.append(data)
            except Exception:
                break

    def _on_release(self, event=None):
        if not self.recording:
            return
        self.recording = False
        self._stop_wave_anim()

        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None

        self.btn.config(bg=self._accent_dim, text="⏳  TRANSCRIBING …")
        self._set_status("● TRANSCRIBING", self._accent_dim)

        if len(self.frames) < 5:
            self._reset_btn()
            return

        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        selected_lang = LANG_CODE.get(self.lang_var.get())
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.audio.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(self.frames))

            kwargs = {"fp16": (DEVICE == "cuda")}
            if selected_lang is not None:
                kwargs["language"] = selected_lang

            result = self.model.transcribe(tmp.name, **kwargs)
            text   = result["text"].strip()
            lang   = result.get("language", "?")

            if text:
                self.root.after(0, self._append_message, text, lang)
            else:
                self.root.after(0, self._append_system, "(no speech detected)")
        except Exception as e:
            self.root.after(0, self._append_error, str(e))
        finally:
            os.unlink(tmp.name)
            self.root.after(0, self._reset_btn)

    # ── Waveform animation ────────────────────────────────────────────────────

    def _start_wave_anim(self):
        self._wave_anim_running = True
        self._animate_wave()

    def _stop_wave_anim(self):
        self._wave_anim_running = False
        for bar in self._wave_bars:
            self.wave_canvas.coords(bar, *self.wave_canvas.coords(bar)[:2],
                                    self.wave_canvas.coords(bar)[2], 20)

    def _animate_wave(self):
        if not self._wave_anim_running:
            return
        import random
        for bar in self._wave_bars:
            x1, _, x2, _ = self.wave_canvas.coords(bar)
            h  = random.randint(4, 32)
            y1 = 20 - h // 2
            y2 = 20 + h // 2
            self.wave_canvas.coords(bar, x1, y1, x2, y2)
        self.root.after(80, self._animate_wave)

    # ── Chat helpers ──────────────────────────────────────────────────────────

    def _append_message(self, text: str, lang: str):
        ts = time.strftime("%H:%M:%S")
        self.chat.config(state="normal")
        self.chat.insert("end", f"\nYOU  ", "you")
        self.chat.insert("end", f"[{ts}] [{lang}]\n", "ts")
        self.chat.insert("end", f"{text}\n", "msg")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _append_system(self, text: str):
        self.chat.config(state="normal")
        self.chat.insert("end", f"{text}\n", "whisper")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _append_error(self, text: str):
        self.chat.config(state="normal")
        self.chat.insert("end", f"[error] {text}\n", "error")
        self.chat.config(state="disabled")
        self.chat.see("end")

    def _reset_btn(self):
        self.btn.config(bg=self._accent, text="⏺  HOLD TO TALK")
        self._set_status("● READY", TEXT_DIM)

    def _set_status(self, text: str, color: str):
        self.status_var.set(text)
        self.status_lbl.config(fg=color)

    def on_close(self):
        self.recording = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        self.audio.terminate()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = PisumathuApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
