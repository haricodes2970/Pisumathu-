# ಪಿಸುಮಾಥು — Pisumathu

> *Kannada for "Whisper"*

A fully offline, push-to-talk speech-to-text overlay for Windows.  
Powered by OpenAI Whisper + NVIDIA CUDA.
just push
---

## Features

- 🎙️ **Push-to-talk** — hold both `Ctrl` keys to record
- 🖥️ **Floating pill overlay** — stays at bottom-center, out of the way
- 🚫 **100% offline** — no cloud, no internet, no API keys
- ⚡ **GPU accelerated** — CUDA via PyTorch (CPU fallback available)
- 🇮🇳 **Kannada support** — `ಪಿಸುಮಾಥು` display + Whisper multilingual
- 🎨 **RGB accent color** — customize to any color with live preview
- 📋 **Chatbox history** — timestamped transcript log
- 💾 **Persistent settings** — color + language saved to `config.json`
- 🧩 **System tray mode** — close to tray, reopen from notification area
- 🚀 **Windows startup option** — optional auto-launch at sign-in

---

## Download (Windows EXE)

Grab the latest release from the [Releases page](../../releases/latest) — no Python needed.

1. Download `Pisumathu-v2.0.2-windows.zip`
2. Extract the folder
3. Run `Pisumathu.exe`

> **Note:** Windows may block the exe on first run.
> Right-click `Pisumathu.exe` → **Properties** → check **Unblock** → **OK**

---

## Installation (from source)

### GPU Version (NVIDIA required)

```bash
# 1. Create venv with Python 3.10
py -3.10 -m venv whisper-env
whisper-env\Scripts\activate

# 2. Install PyTorch with CUDA 12.1
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# 3. Install remaining deps
pip install -r requirements-gpu.txt

# 4. Run
python pisumathu.py
```

### CPU Version (any machine)

```bash
py -3.10 -m venv whisper-env
whisper-env\Scripts\activate
pip install -r requirements-cpu.txt
python pisumathu.py
```

> First run downloads the Whisper `base` model (~139 MB). Subsequent runs use the cached model.

---

## Private Windows App Deployment (for personal use)

Build an EXE on your machine and use it locally without publishing.

```bash
# from project root
whisper-env\Scripts\activate
pip install -r requirements-gpu.txt
pyinstaller --clean --noconfirm pisumathu.spec
```

Output app folder:

```bash
dist\Pisumathu\
```

Run this file:

```bash
dist\Pisumathu\Pisumathu.exe
```

If Windows SmartScreen appears, click `More info` -> `Run anyway` for unsigned local builds.

---

## Usage

1. Launch `python pisumathu.py`
2. Click **▶ START** to show the pill overlay
3. **Hold both Ctrl keys** to start recording
4. **Release** to transcribe
5. Text appears in the chatbox with a timestamp

Tray/startup behavior:

1. Closing the window minimizes Pisumathu to the system tray
2. Right-click tray icon -> `Open Pisumathu` to reopen
3. Right-click tray icon -> `Quit` to fully exit
4. Enable `START WITH WINDOWS` in app UI to auto-run at login
5. Enable `MINIMIZE TO TRAY ON LAUNCH` in app UI to start hidden in tray

---

## Architecture

```
Pisumathu/
├── pisumathu.py          ← Entry point, wires everything
├── audio/
│   └── capture.py        ← PyAudio microphone capture
├── transcription/
│   ├── engine.py         ← Whisper GPU engine
│   └── engine_cpu.py     ← faster-whisper CPU engine
├── ui/
│   ├── main_window.py    ← Main control panel (Tkinter)
│   └── pill.py           ← Floating pill overlay
├── core/
│   └── controller.py     ← App state machine + orchestration
├── config/
│   └── settings.py       ← Config load/save (config.json)
├── requirements-gpu.txt
├── requirements-cpu.txt
└── config.json           ← Auto-created, gitignored
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10 |
| ASR | OpenAI Whisper (base model) |
| GPU | PyTorch + CUDA 12.1 |
| Audio | PyAudio |
| UI | Tkinter |
| Hotkeys | pynput |

---

## License

MIT — see `LICENSE`.

---

## Credits

- [OpenAI Whisper](https://github.com/openai/whisper) (MIT)
- [PyTorch](https://pytorch.org/) (BSD)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT)
- [PyAudio](https://people.csail.mit.edu/hubert/pyaudio/) (MIT)
- [pynput](https://github.com/moses-palmer/pynput) (LGPL)

---

*Built in Bengaluru, Karnataka 🇮🇳*
