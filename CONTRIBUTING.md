# Contributing to Pisumathu

Thank you for your interest in contributing! Pisumathu is an open-source offline speech-to-text overlay — contributions that improve accuracy, performance, UI, or language support are very welcome.

---

## Getting Started

```bash
git clone https://github.com/haricodes2970/Pisumathu.git
cd Pisumathu
py -3.10 -m venv whisper-env
whisper-env\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-gpu.txt
python pisumathu.py
```

---

## Project Layout

| Path | Responsibility |
|------|---------------|
| `pisumathu.py` | Entry point — wires UI ↔ controller |
| `core/controller.py` | State machine, orchestration |
| `audio/capture.py` | PyAudio mic recording |
| `transcription/engine.py` | Whisper GPU inference |
| `transcription/engine_cpu.py` | faster-whisper CPU inference |
| `ui/main_window.py` | Main Tkinter control panel |
| `ui/pill.py` | Floating pill overlay |
| `config/settings.py` | config.json load/save |

---

## Contribution Areas

### 🔧 Bug Fixes
- Check [Issues](https://github.com/haricodes2970/Pisumathu/issues) for open bugs
- Attach repro steps + OS/GPU info

### ⚡ Performance
- VAD (Voice Activity Detection) with Silero or Pyannote
- faster-whisper integration for GPU version
- Reduce model load time

### 🌐 Language Support
- Kannada fine-tuned model integration (`vasista22/whisper-kannada-tiny`)
- IndicWhisper models (AI4Bharat)
- Additional Indian language toggles

### 🎨 UI Improvements
- Draggable pill overlay
- Custom hotkey configuration UI
- Export chatbox to .txt / .md

### 📦 Distribution
- CPU .exe build verification
- GPU .exe build verification
- Demo GIF creation

---

## Code Style

- Python 3.10+
- Type hints on all public methods
- Docstrings on all classes and public methods
- No global mutable state outside `AppController`
- UI updates only through `root.after()` (never call Tkinter from non-main threads)

---

## Pull Request Process

1. Fork the repo
2. Create a branch: `git checkout -b feat/your-feature-name`
3. Make your changes
4. Test manually on Windows 10/11
5. Open a PR with a clear description

---

## Commit Message Format

```
feat: add VAD silence detection
fix: pill overlay position on multi-monitor
refactor: extract timer logic to separate class
docs: update README install steps
```

---

*Pisumathu is built in Bengaluru 🇮🇳 — contributions from the Indian developer community especially welcome!*
