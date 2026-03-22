# Pisumathu — Development Log

> Complete build history from initial commit to v2.0.2

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Tech Stack](#tech-stack)
3. [Project Structure](#project-structure)
4. [Architecture](#architecture)
5. [Module Reference](#module-reference)
6. [Color System](#color-system)
7. [Pill Overlay Design](#pill-overlay-design)
8. [Version History](#version-history)
9. [Known Issues & Fixes](#known-issues--fixes)
10. [Build & Release](#build--release)

---

## Project Overview

**Pisumathu** (ಪಿಸುಮಾಥು) means *Whisper* in Kannada.

It is a fully offline, push-to-talk speech-to-text overlay for Windows. The user holds both `Ctrl` keys, speaks, releases, and the transcribed text is typed directly into whatever window was active — like a browser, chat app, IDE, or terminal.

No cloud. No API keys. No internet required after the first model download.

---

## Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Language | Python | 3.10 |
| ASR Model | OpenAI Whisper | base (139 MB) |
| GPU Acceleration | PyTorch + CUDA | 12.1 |
| Audio Capture | PyAudio | — |
| UI Framework | Tkinter | built-in |
| Hotkey Listener | pynput | — |
| Text Injection | pynput keyboard + Win32 | — |
| Focus Restore | Win32 API (ctypes) | — |
| Config | JSON file | config.json |
| Packaging | PyInstaller | 6.19 |

---

## Project Structure

```
Pisumathu/
├── pisumathu.py              ← Entry point — wires all layers together
│
├── config/
│   ├── __init__.py
│   └── settings.py           ← AppConfig dataclass, ConfigManager, VERSION
│
├── core/
│   ├── __init__.py
│   ├── controller.py         ← AppController, AppState machine
│   └── typer.py              ← Win32 focus capture + pynput text injection
│
├── ui/
│   ├── __init__.py
│   ├── main_window.py        ← Main Tkinter control panel
│   └── pill.py               ← Floating pill overlay (always-on-top)
│
├── audio/
│   ├── __init__.py
│   └── capture.py            ← PyAudio microphone recording
│
├── transcription/
│   ├── __init__.py
│   ├── engine.py             ← Whisper GPU engine
│   └── engine_cpu.py         ← faster-whisper CPU engine
│
├── docs/
│   └── DEVELOPMENT.md        ← This file
│
├── README.md
├── requirements-gpu.txt
├── requirements-cpu.txt
├── config.json               ← Auto-created at runtime, gitignored
└── Pisumathu.spec            ← PyInstaller spec (auto-generated)
```

---

## Architecture

### Layer Diagram

```
┌─────────────────────────────────────────┐
│               pisumathu.py              │  ← bootstraps everything
│            PisumathuApp class           │
└────────────┬────────────────┬───────────┘
             │                │
     ┌───────▼──────┐  ┌──────▼───────────┐
     │ AppController│  │   MainWindow      │
     │ (core/)      │  │   PillOverlay     │
     │              │  │   (ui/)           │
     └──┬───┬───┬───┘  └──────────────────┘
        │   │   │
   ┌────▼┐ ┌▼──────────┐ ┌────────┐
   │Audio│ │Transcription│ │ Typer │
   │     │ │ Engine      │ │(Win32)│
   └─────┘ └─────────────┘ └───────┘
```

### Data Flow

```
User holds Ctrl+Ctrl
        │
        ▼
Typer.capture_focus()     ← snapshot active HWND
AudioCapture.start()      ← begin recording in background thread
AppState → RECORDING
        │
User releases Ctrl
        │
        ▼
AudioCapture.stop()       ← returns .wav path
AppState → TRANSCRIBING
        │
        ▼
TranscriptionEngine.transcribe(wav)   ← Whisper inference
        │
        ▼
on_transcript(text) → MainWindow chatbox
Typer.type_text(text)     ← restore focus + pynput keyboard
AppState → IDLE
```

### Threading Model

- **Main thread** — Tkinter event loop only. All UI updates go through `root.after(0, fn)`.
- **Model load thread** — daemon thread, loads Whisper model at startup.
- **Audio thread** — daemon thread, reads mic in a loop while recording.
- **Transcription thread** — daemon thread, runs Whisper inference after recording stops.
- **Animation thread** (pill) — daemon thread, updates bar heights + spinner angle at 25 fps.

---

## Module Reference

### `config/settings.py`

**`VERSION`** — current app version string (`"2.0.2"`)

**`AppConfig`** — dataclass holding all user settings:

| Field | Type | Default |
|-------|------|---------|
| `r` | int | 0 |
| `g` | int | 229 |
| `b` | int | 255 |
| `language` | str | `"en"` |
| `model_size` | str | `"base"` |
| `device` | str | `"cuda"` |
| `auto_type` | bool | `True` |

Color methods on `AppConfig`:
- `accent_hex()` → `#rrggbb` raw accent
- `light_tint_hex()` → blended with white at 88% (pill background)
- `dark_shade_hex()` → accent × 0.65 (used in main window accents)

**`ConfigManager`** — loads/saves `config.json` at project root. Merges with `DEFAULT_CONFIG` on load, so missing keys always fall back to defaults.

---

### `core/controller.py`

**`AppState`** enum:

```
LOADING → IDLE ↔ RECORDING → TRANSCRIBING → IDLE
                                           ↘ ERROR
```

**`AppController`** orchestrates the pipeline:
- Owns `AudioCapture`, `TranscriptionEngine`, `Typer`
- Starts a hotkey listener (pynput) after model loads
- Hotkey: hold both `Ctrl_L + Ctrl_R` to record, release to transcribe
- Fires callbacks to UI: `on_state_change`, `on_transcript`, `on_timer_tick`, `on_audio_level`, `on_status`
- Config mutations: `update_color()`, `set_language()`, `set_auto_type()`

---

### `core/typer.py`

Handles typing transcribed text into the previously focused window.

**`capture_focus()`** — called the instant the hotkey is pressed, before recording starts. Snapshots `GetForegroundWindow()`.

**`_restore_focus(hwnd)`** — v2.0.1+ safe focus restore:
1. `AllowSetForegroundWindow(hwnd)`
2. `AttachThreadInput(our_tid, target_tid, True)`
3. `BringWindowToTop(hwnd)`
4. `SetForegroundWindow(hwnd)`
5. `AttachThreadInput(..., False)`

> **Why not `ShowWindow`?** Calling `ShowWindow(hwnd, SW_RESTORE)` unconditionally changes window state — it collapses fullscreen and maximized windows. The AttachThreadInput approach gives focus without touching window geometry.

**`type_text(text)`** — restores focus, waits 150 ms settle delay, types via `pynput.keyboard.Controller.type()` which handles full Unicode including Kannada script.

---

### `audio/capture.py`

PyAudio-based mic recorder. Records at **16 kHz mono** (Whisper's expected input format). Writes to a temp `.wav` file via `tempfile.mkstemp`. Reports RMS level per chunk via `on_level` callback (used by pill waveform animation).

---

### `transcription/engine.py`

OpenAI Whisper wrapper. Loads model once at startup. Falls back from CUDA to CPU if no GPU available. Supports language hot-swap (`set_language()`) without reloading the model. Uses `fp16=True` on CUDA, `fp16=False` on CPU. For Kannada (`kn`), passes `language=None` to let Whisper auto-detect (more accurate for Indic scripts).

---

### `ui/main_window.py`

Tkinter control panel, 420×680px, dark theme.

**Layout (top to bottom):**
1. Header — `◈ PISUMATHU  v{VERSION}` in accent color
2. Accent divider (1px, accent color)
3. Chatbox — timestamped transcript log
4. Status bar
5. Second divider
6. **RGB accent color box** — `#161923` background, `#1e2330` border, gradient sliders + swatch
7. Language toggle — EN / KN radio buttons
8. Output toggle — TYPE TO CURSOR checkbox
9. START / STOP button

**`GradientSlider`** — custom Canvas widget (added v2.0.0). Draws a gradient track from `#111111` to the channel end color using 100 interpolated rectangles. White 14px circle thumb. Mouse click+drag interaction. Binds `<Map>` with 50ms `after()` to ensure gradient renders after layout.

**`_apply_accent()`** — called on every slider change. Updates: title color, swatch fill, accent divider bg, button bg/hover.

---

### `ui/pill.py`

Floating always-on-top borderless overlay. Uses `overrideredirect(True)` + `-transparentcolor #010101` for chroma-key transparency.

**States and appearance:**

| State | Width | Border | Dot | Content |
|-------|-------|--------|-----|---------|
| IDLE | 170px | 1px darkShade | 6px darkShade | name (dim) |
| RECORDING | 310px | 2px accent | 7px red blink | bars + name bold + timer |
| TRANSCRIBING | 220px | 1px accent | — | spinner arc + "processing..." |
| LOADING | 170px | 1px darkShade | — | "loading model…" |

**Bar animation** — 8 bars, each with independent min/max heights and staggered delays:

| Bar | Pattern | Delay |
|-----|---------|-------|
| 0 | 2 ↔ 14px | 0.00s |
| 1 | 10 ↔ 3px | 0.12s |
| 2 | 4 ↔ 14px | 0.24s |
| 3 | 6 ↔ 10px | 0.06s |
| 4 | 14 ↔ 4px | 0.18s |
| 5 | 2 ↔ 14px | 0.30s |
| 6 | 6 ↔ 10px | 0.09s |
| 7 | 10 ↔ 3px | 0.15s |

Animation formula: `height = min + (max - min) * (1 - cos(2π * t_adj / 0.55)) / 2`

Red dot blink: `visible when (t % 1.0) < 0.5` — matches CSS `animation: blink 1s step-end infinite`.

---

## Color System

All colors derive from three raw RGB values stored in `AppConfig`.

```
accent    = rgb(r, g, b)
lightTint = rgb(r + (255-r)*0.88,  g + (255-g)*0.88,  b + (255-b)*0.88)
darkShade = rgb(r * 0.35,  g * 0.35,  b * 0.35)
```

The pill computes these inline using the exact spec formula. The main window's `AppConfig.dark_shade_hex()` uses `× 0.65` (less dark, used for button hover states).

Default accent: **`rgb(0, 229, 255)`** — cyan.

---

## Pill Overlay Design

The pill was designed from HTML/CSS reference files and translated to Tkinter Canvas:

- **Shape** — `create_polygon` with `smooth=True` at 12 control points giving a CSS `border-radius: 60px` equivalent
- **Transparency** — window bg `#010101`, `-transparentcolor #010101` makes that color invisible; the pill shape is drawn on top
- **Position** — bottom-center of screen, 40px above taskbar
- **Render loop** — `root.after(40, _render)` ≈ 25 fps, draws to canvas each frame
- **Animation thread** — separate daemon thread updates `_bar_heights[]` and `_spinner_angle` at 25 fps independently of the render loop

---

## Version History

### v2.0.2 — Release Build
- Bumped VERSION to `"2.0.2"`
- PyInstaller `--onedir --windowed` build with `--paths` for local package resolution
- README updated with Download section and Windows Unblock note
- Build produces `Pisumathu-v2.0.2-windows.zip` (~2.3 GB bundled with torch + CUDA)

### v2.0.1 — Focus Fix
- **Bug:** `ShowWindow(hwnd, SW_RESTORE=9)` was minimizing/restoring fullscreen and maximized windows after transcription
- **Fix:** Removed `ShowWindow` entirely. Replaced with `AllowSetForegroundWindow` + `AttachThreadInput` + `BringWindowToTop` + `SetForegroundWindow` + detach. Window state (fullscreen/maximized) is now fully preserved.

### v2.0.0 — Pixel-Perfect Redesign
- **Pill rewrite** — exact match to HTML reference spec:
  - Correct color math: `r + (255-r)*0.88` for tint, `r*0.35` for shade
  - 8-bar waveform with per-bar heights and staggered delays
  - Red dot `#e11d48`, 1s step-end blink
  - IDLE border uses darkShade (not accent)
  - RECORDING border uses full accent, 2px width
  - Non-bold font for idle name; bold for recording name
  - Timer font 9px non-bold
- **RGB slider rewrite** — `GradientSlider` custom Canvas widget replacing `tk.Scale`
  - Gradient track `#111 → end_color` per channel
  - White 14px circle thumb
  - Styled container: `#161923` bg, `#1e2330` 1px border
  - Swatch: 48px circle with `#2a2f3d` 2px border
- **Version label** — `◈ PISUMATHU  v2.0.0` in header
- **Window height** increased from 620 → 680 to accommodate RGB box padding

### v1.x (pre-versioning) — Initial Builds
- `initial commit` — basic push-to-talk concept, single-file
- `466397c` — renamed to `pisumathu.py`, added language selector
- `bf7014e` — RGB color sliders, EN/KN toggle, `config.json` persistence
- `b50e4c5` — rewrote main window UI
- `4a79d71` — floating pill overlay with idle/recording/transcribing states
- `ec6539f` — increased window height to 860 (START button visibility)
- `7b60415` — initial release: pill, whisper, type-to-cursor, RGB system

---

## Known Issues & Fixes

### Device Guard blocks exe on first run
Windows SmartScreen or Device Guard may block unsigned executables.
**Fix:** Right-click `Pisumathu.exe` → Properties → check **Unblock** → OK.

### exe build is ~2.3 GB
PyInstaller bundles the full PyTorch + CUDA runtime + Whisper weights.
GitHub releases have a 2 GB upload limit — host the zip externally (Google Drive, etc.) and link from the release notes.

### GitHub Actions / CI not set up
The build must be run manually on a Windows machine with CUDA drivers installed. PyInstaller requires the target platform to match.

### Kannada font on bare Windows
`Noto Sans Kannada` may not be installed on all Windows machines. If missing, Tkinter falls back to a system font which may not render Kannada glyphs correctly. Bundle or prompt users to install the font.

---

## Build & Release

### From source (development)

```bash
py -3.10 -m venv whisper-env
whisper-env\Scripts\activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install -r requirements-gpu.txt
python pisumathu.py
```

### Build exe

```bash
pip install pyinstaller
pyinstaller --noconfirm --onedir --windowed --name "Pisumathu" \
  --paths "." \
  --hidden-import config.settings \
  --hidden-import core.controller \
  --hidden-import core.typer \
  --hidden-import ui.main_window \
  --hidden-import ui.pill \
  --hidden-import audio.capture \
  --hidden-import transcription.engine \
  pisumathu.py
```

> Must run from the project root inside the activated `whisper-env`.
> `--paths "."` is critical — without it PyInstaller cannot find the local packages.

### Zip for distribution

```powershell
Compress-Archive -Path dist\Pisumathu -DestinationPath Pisumathu-vX.Y.Z-windows.zip
```

### GitHub release

```bash
gh release create vX.Y.Z Pisumathu-vX.Y.Z-windows.zip \
  --title "Pisumathu vX.Y.Z" \
  --notes "Release notes here"
```

---

*Built in Bengaluru, Karnataka 🇮🇳*
