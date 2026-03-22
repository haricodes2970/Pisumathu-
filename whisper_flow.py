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

# ── Config ──────────────────────────────────────────────────────────────────
MODEL_SIZE   = "base"          # tiny | base | small | medium | large
SAMPLE_RATE  = 16000
CHANNELS     = 1
CHUNK        = 1024
FORMAT       = pyaudio.paInt16
DEVICE       = "cuda" if torch.cuda.is_available() else "cpu"

# ── Colours & fonts ──────────────────────────────────────────────────────────
BG          = "#0d0f14"
SURFACE     = "#161923"
ACCENT      = "#00e5ff"
ACCENT_DIM  = "#007a8a"
TEXT        = "#e8eaf0"
TEXT_DIM    = "#5a6070"
DANGER      = "#ff4f5e"
FONT_TITLE  = ("Courier New", 13, "bold")
FONT_CHAT   = ("Courier New", 11)
FONT_BTN    = ("Courier New", 12, "bold")
FONT_STATUS = ("Courier New", 9)

# ── Load model once at startup ───────────────────────────────────────────────
print(f"[whisper-flow] Loading model '{MODEL_SIZE}' on {DEVICE} …")
model = whisper.load_model(MODEL_SIZE, device=DEVICE)
print("[whisper-flow] Model ready.")


class WhisperFlowApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Pisumathu")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry("540x680")

        self.recording   = False
        self.frames      = []
        self.audio       = pyaudio.PyAudio()
        self.stream      = None
        self._build_ui()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self.root, bg=BG)
        hdr.pack(fill="x", padx=24, pady=(20, 0))

        tk.Label(hdr, text="◈ PISUMATHU", font=FONT_TITLE,
                 bg=BG, fg=ACCENT).pack(side="left")

        self.gpu_badge = tk.Label(
            hdr,
            text=f"  GPU  " if DEVICE == "cuda" else "  CPU  ",
            font=("Courier New", 8, "bold"),
            bg=ACCENT if DEVICE == "cuda" else TEXT_DIM,
            fg=BG, padx=6, pady=2
        )
        self.gpu_badge.pack(side="right")

        tk.Label(hdr, text=f"model: {MODEL_SIZE}", font=FONT_STATUS,
                 bg=BG, fg=TEXT_DIM).pack(side="right", padx=10)

        # Divider
        tk.Frame(self.root, bg=ACCENT_DIM, height=1).pack(
            fill="x", padx=24, pady=(12, 0))

        # Chat box
        chat_frame = tk.Frame(self.root, bg=SURFACE,
                              highlightbackground=ACCENT_DIM,
                              highlightthickness=1)
        chat_frame.pack(fill="both", expand=True, padx=24, pady=16)

        self.chat = scrolledtext.ScrolledText(
            chat_frame,
            font=FONT_CHAT,
            bg=SURFACE, fg=TEXT,
            insertbackground=ACCENT,
            relief="flat",
            wrap="word",
            padx=14, pady=12,
            state="disabled",
            cursor="arrow"
        )
        self.chat.pack(fill="both", expand=True)

        # Tag styles
        self.chat.tag_config("you",       foreground=ACCENT,   font=("Courier New", 9, "bold"))
        self.chat.tag_config("msg",       foreground=TEXT,     font=FONT_CHAT)
        self.chat.tag_config("ts",        foreground=TEXT_DIM, font=("Courier New", 8))
        self.chat.tag_config("whisper",   foreground=TEXT_DIM, font=("Courier New", 9, "italic"))
        self.chat.tag_config("error",     foreground=DANGER,   font=("Courier New", 9, "italic"))

        self._append_system("Hold the button below to talk. Release to transcribe.")

        # Status bar
        self.status_var = tk.StringVar(value="● READY")
        self.status_lbl = tk.Label(
            self.root, textvariable=self.status_var,
            font=FONT_STATUS, bg=BG, fg=TEXT_DIM
        )
        self.status_lbl.pack(pady=(0, 6))

        # Waveform canvas (simple animated bars)
        self.wave_canvas = tk.Canvas(
            self.root, bg=BG, height=40, width=492,
            highlightthickness=0
        )
        self.wave_canvas.pack(padx=24)
        self._wave_bars = []
        for i in range(30):
            x = 8 + i * 16
            bar = self.wave_canvas.create_rectangle(
                x, 20, x + 8, 20, fill=ACCENT_DIM, outline=""
            )
            self._wave_bars.append(bar)
        self._wave_anim_running = False

        # Push-to-talk button
        self.btn = tk.Label(
            self.root,
            text="⏺  HOLD TO TALK",
            font=FONT_BTN,
            bg=ACCENT, fg=BG,
            padx=0, pady=18,
            cursor="hand2",
            width=30
        )
        self.btn.pack(padx=24, pady=(10, 22), fill="x")
        self.btn.bind("<ButtonPress-1>",   self._on_press)
        self.btn.bind("<ButtonRelease-1>", self._on_release)

        # Keyboard shortcut: Space
        self.root.bind("<KeyPress-space>",   self._on_press)
        self.root.bind("<KeyRelease-space>", self._on_release)

        tk.Label(self.root, text="or hold  SPACE",
                 font=FONT_STATUS, bg=BG, fg=TEXT_DIM).pack(pady=(0, 12))

    # ── Recording ────────────────────────────────────────────────────────────

    def _on_press(self, event=None):
        if self.recording:
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

        self.btn.config(bg=ACCENT_DIM, text="⏳  TRANSCRIBING …")
        self._set_status("● TRANSCRIBING", ACCENT_DIM)

        if len(self.frames) < 5:
            self._reset_btn()
            return

        threading.Thread(target=self._transcribe, daemon=True).start()

    def _transcribe(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(tmp.name, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.audio.get_sample_size(FORMAT))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b"".join(self.frames))

            result = model.transcribe(tmp.name, fp16=(DEVICE == "cuda"))
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

    # ── Waveform animation ───────────────────────────────────────────────────

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

    # ── Chat helpers ─────────────────────────────────────────────────────────

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
        self.btn.config(bg=ACCENT, text="⏺  HOLD TO TALK")
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


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = WhisperFlowApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
