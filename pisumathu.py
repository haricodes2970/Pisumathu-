import tkinter as tk
from tkinter import scrolledtext
import threading
import tempfile
import os
import wave
import pyaudio
import whisper
import torch
import time
import json

# ── Whisper config (hardcoded) ────────────────────────────────────────────────
MODEL_SIZE  = "base"
SAMPLE_RATE = 16000
CHANNELS    = 1
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
DEVICE      = "cuda" if torch.cuda.is_available() else "cpu"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ── Theme constants ───────────────────────────────────────────────────────────
BG      = "#0d0f14"
SURFACE = "#161923"
TEXT    = "#e8eaf0"
TEXT_DIM= "#5a6070"
DANGER  = "#ff4f5e"
WARN    = "#ffb300"

DEFAULT_RGB = (0, 229, 255)
DIM_FACTOR  = 0.43

FONT_TITLE  = ("Courier New", 13, "bold")
FONT_CHAT   = ("Courier New", 11)
FONT_BTN    = ("Courier New", 12, "bold")
FONT_SMALL  = ("Courier New", 9)
FONT_TINY   = ("Courier New", 7)


def rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def make_dim(r, g, b):
    return rgb_to_hex(r * DIM_FACTOR, g * DIM_FACTOR, b * DIM_FACTOR)


# ── Load Whisper model at startup ─────────────────────────────────────────────
print(f"[pisumathu] loading '{MODEL_SIZE}' on {DEVICE} …")
model = whisper.load_model(MODEL_SIZE, device=DEVICE)
print("[pisumathu] model ready.")


class PisumathuApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pisumathu")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("480x700")

        # state
        self.recording    = False
        self.frames       = []
        self.audio        = pyaudio.PyAudio()
        self.stream       = None
        self.pill_overlay = None   # set when pill is launched
        self._pill_en     = True   # True=English False=Kannada

        # accent color
        self._ar, self._ag, self._ab = DEFAULT_RGB
        self._accent     = rgb_to_hex(*DEFAULT_RGB)
        self._accent_dim = make_dim(*DEFAULT_RGB)

        self._load_config()
        self._build_ui()

    # ── Config ────────────────────────────────────────────────────────────────

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            cfg = json.load(open(CONFIG_FILE))
            r, g, b = cfg.get("accent_rgb", list(DEFAULT_RGB))
            self._ar, self._ag, self._ab = int(r), int(g), int(b)
            self._accent     = rgb_to_hex(self._ar, self._ag, self._ab)
            self._accent_dim = make_dim(self._ar, self._ag, self._ab)
            self._pill_en    = cfg.get("pill_lang_en", True)
        except Exception:
            pass

    def _save_config(self):
        try:
            json.dump({"accent_rgb": [self._ar, self._ag, self._ab],
                       "pill_lang_en": self._pill_en},
                      open(CONFIG_FILE, "w"), indent=2)
        except Exception:
            pass

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── HEADER ───────────────────────────────────────────────────────────
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        self.hdr_title = tk.Label(hdr, text="◈ PISUMATHU",
                                  font=FONT_TITLE, bg=BG, fg=self._accent)
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
                                  font=FONT_SMALL, bg=BG, fg=TEXT_DIM)
        self.model_lbl.pack(side="right", padx=10)

        # ── DIVIDER ───────────────────────────────────────────────────────────
        self.divider = tk.Frame(self.root, bg=self._accent_dim, height=1)
        self.divider.pack(fill="x", padx=24, pady=(12, 0))

        # ── CHATBOX ───────────────────────────────────────────────────────────
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
        self._append_system("Click ▶ START to launch the pill overlay.")

        # ── STATUS ────────────────────────────────────────────────────────────
        self.status_var = tk.StringVar(value="● READY")
        self.status_lbl = tk.Label(self.root, textvariable=self.status_var,
                                   font=FONT_SMALL, bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(pady=(0, 4))

        # ── RGB COLOR SECTION ─────────────────────────────────────────────────
        self._build_rgb_section()

        # ── DIVIDER ───────────────────────────────────────────────────────────
        self.divider2 = tk.Frame(self.root, bg=self._accent_dim, height=1)
        self.divider2.pack(fill="x", padx=24, pady=(10, 0))

        # ── START / STOP BUTTON ───────────────────────────────────────────────
        self.start_btn = tk.Label(
            self.root, text="▶  START",
            font=FONT_BTN, bg=self._accent, fg=BG,
            padx=0, pady=18, cursor="hand2", width=30
        )
        self.start_btn.pack(padx=24, pady=(12, 20), fill="x")
        self.start_btn.bind("<Button-1>", self._on_start_stop)

    def _build_rgb_section(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="x", padx=24, pady=(6, 0))

        # Label
        tk.Label(outer, text="ACCENT COLOR", font=FONT_TINY,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 6))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="x")

        # Sliders column
        sliders = tk.Frame(inner, bg=BG)
        sliders.pack(side="left", fill="x", expand=True)

        self._r_var = tk.IntVar(value=self._ar)
        self._g_var = tk.IntVar(value=self._ag)
        self._b_var = tk.IntVar(value=self._ab)

        slider_cfg = [
            ("R", "#ff5555", self._r_var, "_ar"),
            ("G", "#55ff88", self._g_var, "_ag"),
            ("B", "#5599ff", self._b_var, "_ab"),
        ]
        for lbl, color, var, attr in slider_cfg:
            row = tk.Frame(sliders, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=("Courier New", 9, "bold"),
                     bg=BG, fg=color, width=2).pack(side="left")
            sl = tk.Scale(
                row, variable=var, from_=0, to=255,
                orient="horizontal", length=280, showvalue=False,
                bg=BG, troughcolor=SURFACE,
                highlightthickness=0, bd=0,
                activebackground=color,
                command=lambda _v, _a=attr, _var=var: self._on_rgb_change(_a, _var),
            )
            sl.pack(side="left", padx=(4, 0))

        # Swatch circle (48x48) + EN/KN toggle
        right = tk.Frame(inner, bg=BG)
        right.pack(side="left", padx=(12, 0), anchor="center")

        self.swatch_canvas = tk.Canvas(right, width=48, height=48,
                                       bg=BG, highlightthickness=0)
        self.swatch_canvas.pack()
        self._swatch_oval = self.swatch_canvas.create_oval(
            2, 2, 46, 46, fill=self._accent, outline=self._accent_dim, width=2
        )

        self.lang_toggle = tk.Label(
            right,
            text="EN" if self._pill_en else "KN",
            font=("Courier New", 8, "bold"),
            bg=self._accent_dim, fg=TEXT,
            padx=8, pady=4, cursor="hand2"
        )
        self.lang_toggle.pack(pady=(8, 0))
        self.lang_toggle.bind("<Button-1>", self._toggle_pill_lang)

    # ── RGB live update ───────────────────────────────────────────────────────

    def _on_rgb_change(self, attr, var):
        setattr(self, attr, var.get())
        self._accent     = rgb_to_hex(self._ar, self._ag, self._ab)
        self._accent_dim = make_dim(self._ar, self._ag, self._ab)
        self._apply_accent()
        self._save_config()

    def _apply_accent(self):
        ac  = self._accent
        dim = self._accent_dim
        self.hdr_title.config(fg=ac)
        if DEVICE == "cuda":
            self.gpu_badge.config(bg=ac)
        self.divider.config(bg=dim)
        self.divider2.config(bg=dim)
        self.chat_frame.config(highlightbackground=dim)
        self.chat.tag_config("you", foreground=ac)
        self.swatch_canvas.itemconfig(self._swatch_oval, fill=ac, outline=dim)
        self.lang_toggle.config(bg=dim)
        # start button only if not mid-recording
        if self.start_btn.cget("text").startswith("▶"):
            self.start_btn.config(bg=ac)
        # pill overlay
        if self.pill_overlay:
            try:
                self.pill_overlay.update_accent(ac, dim)
            except Exception:
                self.pill_overlay = None

    # ── EN/KN toggle ─────────────────────────────────────────────────────────

    def _toggle_pill_lang(self, event=None):
        self._pill_en = not self._pill_en
        self.lang_toggle.config(text="EN" if self._pill_en else "KN")
        if self.pill_overlay:
            try:
                self.pill_overlay.update_lang(self._pill_en)
            except Exception:
                self.pill_overlay = None
        self._save_config()

    # ── START / STOP pill ─────────────────────────────────────────────────────

    def _on_start_stop(self, event=None):
        if self.pill_overlay is None:
            self._launch_pill()
        else:
            self._stop_pill()

    def _launch_pill(self):
        # Placeholder — pill overlay implemented in next step
        self.start_btn.config(text="■  STOP", bg=DANGER)
        self._append_system("Pill overlay started. Hold both Ctrl keys to record.")

    def _stop_pill(self):
        if self.pill_overlay:
            try:
                self.pill_overlay.close()
            except Exception:
                pass
            self.pill_overlay = None
        self.start_btn.config(text="▶  START", bg=self._accent)
        self._append_system("Pill overlay stopped.")

    # ── Transcription (called by pill overlay) ────────────────────────────────

    def transcribe_audio(self, frames):
        """Called from pill overlay after recording. Runs in background thread."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.audio.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(frames))
            result = model.transcribe(tmp.name, fp16=(DEVICE == "cuda"), language="en")
            text   = result["text"].strip()
            lang   = result.get("language", "en")
            if text:
                self.root.after(0, self._append_message, text, lang)
            else:
                self.root.after(0, self._append_system, "(no speech detected)")
        except Exception as e:
            self.root.after(0, self._append_error, str(e))
        finally:
            os.unlink(tmp.name)

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

    def _set_status(self, text: str, color: str):
        self.status_var.set(text)
        self.status_lbl.config(fg=color)

    def on_close(self):
        self._stop_pill()
        self.audio.terminate()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = PisumathuApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
