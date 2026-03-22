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
import random

try:
    from pynput import keyboard as pynput_kb
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    print("[pisumathu] pynput not found — run: pip install pynput")

# ── Whisper config (hardcoded) ────────────────────────────────────────────────
MODEL_SIZE  = "base"
SAMPLE_RATE = 16000
CHANNELS    = 1
CHUNK       = 1024
FORMAT      = pyaudio.paInt16
DEVICE      = "cuda" if torch.cuda.is_available() else "cpu"
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
TRANS       = "#010101"   # transparent key color for Windows overlay

# ── Theme ─────────────────────────────────────────────────────────────────────
BG       = "#0d0f14"
SURFACE  = "#161923"
TEXT     = "#e8eaf0"
TEXT_DIM = "#5a6070"
DANGER   = "#e11d48"
WARN     = "#ffb300"

DEFAULT_RGB = (0, 229, 255)
DIM_FACTOR  = 0.43

FONT_TITLE = ("Courier New", 13, "bold")
FONT_CHAT  = ("Courier New", 11)
FONT_BTN   = ("Courier New", 12, "bold")
FONT_SMALL = ("Courier New", 9)
FONT_TINY  = ("Courier New", 7)


def rgb_to_hex(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"

def make_dim(r, g, b):
    return rgb_to_hex(r * DIM_FACTOR, g * DIM_FACTOR, b * DIM_FACTOR)

def make_tint(r, g, b, f=0.88):
    return rgb_to_hex(r + (255-r)*f, g + (255-g)*f, b + (255-b)*f)

def make_dark(r, g, b, f=0.35):
    return rgb_to_hex(r*f, g*f, b*f)


print(f"[pisumathu] loading '{MODEL_SIZE}' on {DEVICE} …")
model = whisper.load_model(MODEL_SIZE, device=DEVICE)
print("[pisumathu] model ready.")


# ══════════════════════════════════════════════════════════════════════════════
#  PILL OVERLAY
# ══════════════════════════════════════════════════════════════════════════════

class PillOverlay:
    H       = 38   # pill height px
    PAD     = 4    # canvas margin around pill
    IDLE_W  = 160  # pill width — idle
    REC_W   = 215  # pill width — recording
    TRANS_W = 175  # pill width — transcribing
    N_BARS  = 8
    BAR_W   = 2
    BAR_GAP = 2

    def __init__(self, app):
        self.app         = app
        self._ar         = app._ar
        self._ag         = app._ag
        self._ab         = app._ab
        self._pill_en    = app._pill_en
        self._state      = "idle"
        self._recording  = False
        self._rec_frames = []
        self._timer_sec  = 0
        self._ctrl_l     = False
        self._ctrl_r     = False
        self._blink_on   = True

        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANS)
        self.win.attributes("-transparentcolor", TRANS)

        self.canvas = tk.Canvas(self.win, bg=TRANS, highlightthickness=0, bd=0)
        self.canvas.pack()

        self._show_idle()
        self._setup_keyboard()

    # ── Color helpers ─────────────────────────────────────────────────────────

    def _c(self):
        r, g, b = self._ar, self._ag, self._ab
        return dict(
            accent=rgb_to_hex(r, g, b),
            tint=make_tint(r, g, b),
            dark=make_dark(r, g, b),
            dim=make_dim(r, g, b),
        )

    def _name_and_font(self):
        if self._pill_en:
            return "PISUMATHU", ("Courier New", 11, "bold")
        return "ಪಿಸುಮಾಥು", ("Noto Sans Kannada", 11, "bold")

    # ── Capsule drawing ───────────────────────────────────────────────────────

    def _draw_capsule(self, pill_w, bg, border, bw=1):
        """Draw filled pill on canvas. Returns vertical center y."""
        p  = self.PAD
        x1, y1 = p, p
        x2, y2 = p + pill_w, p + self.H
        r  = self.H // 2
        cy = (y1 + y2) // 2

        # Fill: two half-circle ovals + center rectangle
        self.canvas.create_oval(x1, y1, x1+self.H, y2, fill=bg, outline="")
        self.canvas.create_oval(x2-self.H, y1, x2, y2, fill=bg, outline="")
        self.canvas.create_rectangle(x1+r, y1, x2-r, y2, fill=bg, outline="")

        # Border arcs
        self.canvas.create_arc(x1, y1, x1+self.H, y2,
                               start=90, extent=180, style="arc",
                               outline=border, width=bw)
        self.canvas.create_arc(x2-self.H, y1, x2, y2,
                               start=270, extent=180, style="arc",
                               outline=border, width=bw)
        # Border straight lines top / bottom
        self.canvas.create_line(x1+r, y1, x2-r, y1, fill=border, width=bw)
        self.canvas.create_line(x1+r, y2, x2-r, y2, fill=border, width=bw)

        return cy

    # ── States ────────────────────────────────────────────────────────────────

    def _resize(self, pill_w):
        cw = pill_w + self.PAD * 2
        ch = self.H  + self.PAD * 2
        self.canvas.config(width=cw, height=ch)
        sw = self.win.winfo_screenwidth()
        sh = self.win.winfo_screenheight()
        x  = (sw - cw) // 2
        y  = sh - ch - 80
        self.win.geometry(f"{cw}x{ch}+{x}+{y}")

    def _show_idle(self):
        self._state = "idle"
        c = self._c()
        name, font = self._name_and_font()
        self._resize(self.IDLE_W)
        self.canvas.delete("all")

        cy = self._draw_capsule(self.IDLE_W, c["tint"], c["dark"], bw=1)
        x  = self.PAD + 16   # left padding

        # Dim dot 6×6
        self.canvas.create_oval(x, cy-3, x+6, cy+3, fill=c["dark"], outline="")
        x += 6 + 6

        # Name
        self.canvas.create_text(x, cy, text=name, font=font,
                                fill=c["dark"], anchor="w")

    def _show_recording(self):
        self._state  = "recording"
        self._blink_on = True
        c = self._c()
        name, font = self._name_and_font()
        self._resize(self.REC_W)
        self.canvas.delete("all")

        cy = self._draw_capsule(self.REC_W, c["tint"], c["accent"], bw=2)
        p  = self.PAD
        x  = p + 12   # left padding 12 px

        # Red blinking dot 7×7
        self._blink_dot = self.canvas.create_oval(
            x, cy-4, x+7, cy+3, fill=DANGER, outline="")
        x += 7 + 5

        # Waveform bars
        self._wave_bar_ids = []
        self._wave_bars_x  = []
        for i in range(self.N_BARS):
            bx  = x + i * (self.BAR_W + self.BAR_GAP)
            bid = self.canvas.create_rectangle(
                bx, cy-4, bx+self.BAR_W, cy+4, fill=c["accent"], outline="")
            self._wave_bar_ids.append(bid)
            self._wave_bars_x.append(bx)
        x += self.N_BARS * (self.BAR_W + self.BAR_GAP) - self.BAR_GAP + 5

        # Name text
        self.canvas.create_text(x, cy, text=name, font=font,
                                fill=c["dark"], anchor="w")

        # Timer — right-aligned inside pill
        timer_x = p + self.REC_W - 12
        self._timer_id = self.canvas.create_text(
            timer_x, cy, text="00:00",
            font=("Courier New", 9), fill=c["dark"], anchor="e")

        self._blink_loop()
        self._wave_loop()
        self._timer_loop()

    def _show_transcribing(self):
        self._state = "transcribing"
        c = self._c()
        self._resize(self.TRANS_W)
        self.canvas.delete("all")

        cy = self._draw_capsule(self.TRANS_W, c["tint"], c["dim"], bw=1)
        self._proc_id = self.canvas.create_text(
            self.PAD + self.TRANS_W // 2, cy,
            text="processing…",
            font=("Courier New", 10, "italic"),
            fill=c["dark"], anchor="center")
        self._proc_dots = 0
        self._proc_loop()

    # ── Animation loops ───────────────────────────────────────────────────────

    def _blink_loop(self):
        if self._state != "recording":
            return
        self._blink_on = not self._blink_on
        color = DANGER if self._blink_on else self._c()["tint"]
        try:
            self.canvas.itemconfig(self._blink_dot, fill=color, outline=color)
        except Exception:
            return
        self.win.after(500, self._blink_loop)

    def _wave_loop(self):
        if self._state != "recording":
            return
        c  = self._c()
        cy = self.PAD + self.H // 2
        for bx, bid in zip(self._wave_bars_x, self._wave_bar_ids):
            h = random.randint(2, 14)
            try:
                self.canvas.coords(bid, bx, cy - h//2, bx+self.BAR_W, cy + h//2)
                self.canvas.itemconfig(bid, fill=c["accent"])
            except Exception:
                return
        self.win.after(80, self._wave_loop)

    def _timer_loop(self):
        if self._state != "recording":
            return
        self._timer_sec += 1
        mm, ss = divmod(self._timer_sec, 60)
        try:
            self.canvas.itemconfig(self._timer_id, text=f"{mm:02d}:{ss:02d}")
        except Exception:
            return
        self.win.after(1000, self._timer_loop)

    def _proc_loop(self):
        if self._state != "transcribing":
            return
        dots = "." * (self._proc_dots % 4)
        try:
            self.canvas.itemconfig(self._proc_id, text=f"processing{dots}")
        except Exception:
            return
        self._proc_dots += 1
        self.win.after(400, self._proc_loop)

    # ── Keyboard (pynput global listener) ─────────────────────────────────────

    def _setup_keyboard(self):
        if not HAS_PYNPUT:
            self._append_warning()
            return

        def on_press(key):
            if key == pynput_kb.Key.ctrl_l:
                if not self._ctrl_l:
                    self._ctrl_l = True
                    if self._ctrl_r and not self._recording:
                        self.win.after(0, self._start_recording)
            elif key == pynput_kb.Key.ctrl_r:
                if not self._ctrl_r:
                    self._ctrl_r = True
                    if self._ctrl_l and not self._recording:
                        self.win.after(0, self._start_recording)

        def on_release(key):
            if key == pynput_kb.Key.ctrl_l:
                self._ctrl_l = False
                if self._recording:
                    self.win.after(0, self._stop_recording)
            elif key == pynput_kb.Key.ctrl_r:
                self._ctrl_r = False
                if self._recording:
                    self.win.after(0, self._stop_recording)

        self._kb = pynput_kb.Listener(on_press=on_press, on_release=on_release)
        self._kb.daemon = True
        self._kb.start()

    def _append_warning(self):
        self.app.root.after(0, self.app._append_system,
                            "⚠ pynput missing — pip install pynput")

    # ── Recording ─────────────────────────────────────────────────────────────

    def _start_recording(self):
        if self._recording:
            return
        self._recording   = True
        self._rec_frames  = []
        self._timer_sec   = 0
        self._show_recording()

        self._stream = self.app.audio.open(
            format=FORMAT, channels=CHANNELS,
            rate=SAMPLE_RATE, input=True,
            frames_per_buffer=CHUNK)
        threading.Thread(target=self._record_loop, daemon=True).start()

    def _record_loop(self):
        while self._recording:
            try:
                data = self._stream.read(CHUNK, exception_on_overflow=False)
                self._rec_frames.append(data)
            except Exception:
                break

    def _stop_recording(self):
        if not self._recording:
            return
        self._recording = False
        try:
            self._stream.stop_stream()
            self._stream.close()
        except Exception:
            pass

        frames = list(self._rec_frames)
        if len(frames) < 5:
            self.win.after(0, self._show_idle)
            return

        self.win.after(0, self._show_transcribing)
        threading.Thread(target=self._run_transcription,
                         args=(frames,), daemon=True).start()

    def _run_transcription(self, frames):
        self.app.transcribe_audio(frames)
        self.win.after(0, self._show_idle)

    # ── Public API (called by PisumathuApp) ───────────────────────────────────

    def update_accent(self, accent, dim):
        self._ar, self._ag, self._ab = self.app._ar, self.app._ag, self.app._ab
        if self._state == "idle":
            self._show_idle()
        # recording/transcribing loops read _c() dynamically — no action needed

    def update_lang(self, is_en):
        self._pill_en = is_en
        if self._state == "idle":
            self._show_idle()

    def close(self):
        self._recording = False
        self._state     = "closed"
        if HAS_PYNPUT and hasattr(self, "_kb"):
            try:
                self._kb.stop()
            except Exception:
                pass
        try:
            self.win.destroy()
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

class PisumathuApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pisumathu")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("480x700")

        self.audio        = pyaudio.PyAudio()
        self.pill_overlay = None
        self._pill_en     = True

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

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
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
            fg=BG, padx=6, pady=2)
        self.gpu_badge.pack(side="right")

        self.model_lbl = tk.Label(hdr, text=f"model: {MODEL_SIZE}",
                                  font=FONT_SMALL, bg=BG, fg=TEXT_DIM)
        self.model_lbl.pack(side="right", padx=10)

        # Divider
        self.divider = tk.Frame(self.root, bg=self._accent_dim, height=1)
        self.divider.pack(fill="x", padx=24, pady=(12, 0))

        # Chatbox
        self.chat_frame = tk.Frame(self.root, bg=SURFACE,
                                   highlightbackground=self._accent_dim,
                                   highlightthickness=1)
        self.chat_frame.pack(fill="both", expand=True, padx=24, pady=16)

        self.chat = scrolledtext.ScrolledText(
            self.chat_frame, font=FONT_CHAT,
            bg=SURFACE, fg=TEXT, insertbackground=self._accent,
            relief="flat", wrap="word", padx=14, pady=12,
            state="disabled", cursor="arrow")
        self.chat.pack(fill="both", expand=True)
        self.chat.tag_config("you",     foreground=self._accent, font=("Courier New", 9, "bold"))
        self.chat.tag_config("msg",     foreground=TEXT,         font=FONT_CHAT)
        self.chat.tag_config("ts",      foreground=TEXT_DIM,     font=("Courier New", 8))
        self.chat.tag_config("whisper", foreground=TEXT_DIM,     font=("Courier New", 9, "italic"))
        self.chat.tag_config("error",   foreground=DANGER,       font=("Courier New", 9, "italic"))
        self._append_system("Click ▶ START — then hold both Ctrl keys to record.")

        # Status
        self.status_var = tk.StringVar(value="● READY")
        self.status_lbl = tk.Label(self.root, textvariable=self.status_var,
                                   font=FONT_SMALL, bg=BG, fg=TEXT_DIM)
        self.status_lbl.pack(pady=(0, 4))

        # RGB section
        self._build_rgb_section()

        # Divider 2
        self.divider2 = tk.Frame(self.root, bg=self._accent_dim, height=1)
        self.divider2.pack(fill="x", padx=24, pady=(10, 0))

        # Start / Stop button
        self.start_btn = tk.Label(
            self.root, text="▶  START",
            font=FONT_BTN, bg=self._accent, fg=BG,
            padx=0, pady=18, cursor="hand2", width=30)
        self.start_btn.pack(padx=24, pady=(12, 20), fill="x")
        self.start_btn.bind("<Button-1>", self._on_start_stop)

    def _build_rgb_section(self):
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="x", padx=24, pady=(6, 0))

        tk.Label(outer, text="ACCENT COLOR", font=FONT_TINY,
                 bg=BG, fg=TEXT_DIM).pack(anchor="w", pady=(0, 6))

        inner = tk.Frame(outer, bg=BG)
        inner.pack(fill="x")

        sliders = tk.Frame(inner, bg=BG)
        sliders.pack(side="left", fill="x", expand=True)

        self._r_var = tk.IntVar(value=self._ar)
        self._g_var = tk.IntVar(value=self._ag)
        self._b_var = tk.IntVar(value=self._ab)

        for lbl, color, var, attr in [
            ("R", "#ff5555", self._r_var, "_ar"),
            ("G", "#55ff88", self._g_var, "_ag"),
            ("B", "#5599ff", self._b_var, "_ab"),
        ]:
            row = tk.Frame(sliders, bg=BG)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=lbl, font=("Courier New", 9, "bold"),
                     bg=BG, fg=color, width=2).pack(side="left")
            tk.Scale(
                row, variable=var, from_=0, to=255,
                orient="horizontal", length=280, showvalue=False,
                bg=BG, troughcolor=SURFACE, highlightthickness=0, bd=0,
                activebackground=color,
                command=lambda _v, _a=attr, _var=var: self._on_rgb_change(_a, _var),
            ).pack(side="left", padx=(4, 0))

        # Swatch + toggle
        right = tk.Frame(inner, bg=BG)
        right.pack(side="left", padx=(12, 0), anchor="center")

        self.swatch_canvas = tk.Canvas(right, width=48, height=48,
                                       bg=BG, highlightthickness=0)
        self.swatch_canvas.pack()
        self._swatch_oval = self.swatch_canvas.create_oval(
            2, 2, 46, 46, fill=self._accent, outline=self._accent_dim, width=2)

        self.lang_toggle = tk.Label(
            right,
            text="EN" if self._pill_en else "KN",
            font=("Courier New", 8, "bold"),
            bg=self._accent_dim, fg=TEXT,
            padx=8, pady=4, cursor="hand2")
        self.lang_toggle.pack(pady=(8, 0))
        self.lang_toggle.bind("<Button-1>", self._toggle_pill_lang)

    # ── Accent update ─────────────────────────────────────────────────────────

    def _on_rgb_change(self, attr, var):
        setattr(self, attr, var.get())
        self._accent     = rgb_to_hex(self._ar, self._ag, self._ab)
        self._accent_dim = make_dim(self._ar, self._ag, self._ab)
        self._apply_accent()
        self._save_config()

    def _apply_accent(self):
        ac, dim = self._accent, self._accent_dim
        self.hdr_title.config(fg=ac)
        if DEVICE == "cuda":
            self.gpu_badge.config(bg=ac)
        self.divider.config(bg=dim)
        self.divider2.config(bg=dim)
        self.chat_frame.config(highlightbackground=dim)
        self.chat.tag_config("you", foreground=ac)
        self.swatch_canvas.itemconfig(self._swatch_oval, fill=ac, outline=dim)
        self.lang_toggle.config(bg=dim)
        if self.start_btn.cget("text").startswith("▶"):
            self.start_btn.config(bg=ac)
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

    # ── Start / Stop pill ─────────────────────────────────────────────────────

    def _on_start_stop(self, event=None):
        if self.pill_overlay is None:
            self._launch_pill()
        else:
            self._stop_pill()

    def _launch_pill(self):
        self.pill_overlay = PillOverlay(self)
        self.start_btn.config(text="■  STOP", bg=DANGER)
        self._append_system("Pill running — hold both Ctrl keys to record.")

    def _stop_pill(self):
        if self.pill_overlay:
            try:
                self.pill_overlay.close()
            except Exception:
                pass
            self.pill_overlay = None
        self.start_btn.config(text="▶  START", bg=self._accent)
        self._append_system("Pill stopped.")

    # ── Transcription (called by PillOverlay in background thread) ────────────

    def transcribe_audio(self, frames):
        self.root.after(0, self._set_status, "● TRANSCRIBING", TEXT_DIM)
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
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            self.root.after(0, self._set_status, "● READY", TEXT_DIM)

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
