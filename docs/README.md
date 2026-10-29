# Pisumathu Project Guide

This document is a complete, practical reference for the Pisumathu project.
It explains what the app does, why it is useful, how it is structured, how to run/build it, which packages are used, and where to debug common issues.

## 1) What Is Pisumathu

Pisumathu is an offline speech-to-text desktop app for Windows.
It lets you press and hold both Ctrl keys to record your voice, transcribe speech locally with Whisper, and optionally type the result into the currently focused app.

Core goals:
- Fully offline transcription
- Fast push-to-talk workflow
- Minimal floating UI while recording
- Practical daily-use tool for coding, chat, notes, and commands

## 2) Why This Is Useful

- Privacy-first: no cloud API calls for transcription.
- Productivity: quick voice input without opening a separate recorder.
- Works system-wide: can type transcribed text into other applications.
- Flexible runtime: supports tray mode, startup options, and model switching.
- GPU acceleration available for better speed.

## 3) Main Features

- Push-to-talk hotkey using both Ctrl keys.
- Floating pill overlay with visual recording/transcribing states.
- Transcript history in the app window.
- Auto-type transcribed output into active cursor location.
- Accent color customization (RGB sliders).
- Language selection (EN/KN).
- Whisper model size selection (base/small/medium).
- System tray support (open/quit).
- Start with Windows option.
- Start minimized to tray option.
- GPU support with CPU fallback path.

## 4) Current Project Structure

Top-level layout:

```
Pisumathu/
  audio/
    __init__.py
    capture.py
  config/
    __init__.py
    settings.py
  core/
    __init__.py
    controller.py
    typer.py
  docs/
    DEVELOPMENT.md
    PROJECT_GUIDE.md
  transcription/
    __init__.py
    engine.py
    engine_cpu.py
  ui/
    __init__.py
    main_window.py
    pill.py
  capture.py
  controller.py
  engine.py
  engine_cpu.py
  main_window.py
  pill.py
  pisumathu.py
  settings.py
  typer.py
  config.json
  requirements-gpu.txt
  requirements-cpu.txt
  pisumathu.spec
  README.md
```

Notes:
- The folder-based modules under audio/config/core/transcription/ui are the primary code paths.
- Some duplicate top-level files exist from earlier layout stages.
- Entry point for app launch is pisumathu.py.

## 5) Important Modules and Responsibilities

- pisumathu.py
  - App bootstrap and lifecycle wiring.
  - Integrates controller, UI, tray behavior, and startup options.

- core/controller.py
  - Central state machine and orchestration.
  - Coordinates recording, transcription, status updates, callbacks, and runtime model changes.

- transcription/engine.py
  - Whisper model loading and transcription on GPU path.
  - Handles device selection and transcription call parameters.

- audio/capture.py
  - Microphone capture and WAV generation.

- core/typer.py
  - Focus restore and typing output into target window.

- ui/main_window.py
  - Main Tkinter control panel.
  - Settings controls, transcript panel, model selector, startup toggles.

- ui/pill.py
  - Floating pill overlay and state animations.

- ui/tray.py
  - System tray icon, menu, open/quit actions.

- core/startup.py
  - Windows startup registry integration (HKCU Run key).

- config/settings.py
  - Config dataclass, defaults, load/save behavior.

## 6) App Flow (High Level)

1. App starts and loads config.
2. Whisper model is loaded.
3. User triggers recording via hotkey.
4. Audio is captured to WAV.
5. WAV is transcribed.
6. Transcript is shown in UI.
7. If auto-type is enabled, text is typed to active target app.

## 7) Configuration

Configuration file: config.json (project root, runtime file).

Typical keys:
- r, g, b: accent color channels
- language: en or kn
- model_size: base, small, medium
- device: cuda or cpu
- auto_type: true/false
- start_with_windows: true/false
- start_in_tray: true/false

Default-safe profile:

```json
{
  "r": 0,
  "g": 229,
  "b": 255,
  "language": "en",
  "model_size": "base",
  "device": "cuda",
  "auto_type": true,
  "start_with_windows": false,
  "start_in_tray": false
}
```

Important:
- config.json is ignored by git (local runtime state).
- If this file gets corrupted or has unstable settings, app behavior may break until reset.

## 8) Dependencies and Packages

### GPU requirements (requirements-gpu.txt)
- openai-whisper>=20231117
- pyaudio>=0.2.14
- pynput>=1.7.6
- pystray>=0.19.5
- Pillow>=10.0.0

Also required manually for GPU build:
- torch
- torchvision
- torchaudio
Installed from CUDA 12.1 index URL.

### CPU requirements (requirements-cpu.txt)
- faster-whisper>=1.0.0
- pyaudio>=0.2.14
- pynput>=1.7.6
- pystray>=0.19.5
- Pillow>=10.0.0

### Build tooling
- PyInstaller (used to produce Windows EXE)

## 9) Setup and Run

### A) GPU mode

1. Create and activate Python 3.10 virtual environment.
2. Install torch stack from CUDA 12.1 wheel index.
3. Install requirements-gpu.txt.
4. Run python pisumathu.py.

### B) CPU mode

1. Create and activate Python 3.10 virtual environment.
2. Install requirements-cpu.txt.
3. Run python pisumathu.py.

## 10) Build EXE (Private Windows App)

From project root with environment activated:

```powershell
pyinstaller --clean --noconfirm pisumathu.spec
```

Output:
- dist/Pisumathu/Pisumathu.exe

If build fails with "Access is denied" on EXE:
- Close running Pisumathu process first.
- Then rebuild.

## 11) Troubleshooting

### Transcription not working

Check in this order:

1. Config sanity
- Reset language to en.
- Reset model_size to base.
- Verify config.json is valid JSON.

2. Model/device
- Try base model first.
- If cuda issues happen, switch to cpu and retest.

3. Mic capture
- Confirm microphone permissions and input device.
- Check audio capture path and WAV creation.

4. Runtime logs
- Watch console logs for model load/transcribe errors.

Known risky area:
- If language is kn, transcription engine has special behavior that may produce unstable results depending on model/settings environment.

### EXE build fails

- Ensure no running instance locks dist output files.
- Clear build and dist folders, then rebuild.
- Confirm required packages are installed in the active environment.

## 12) Security and Privacy Notes

- Transcription is offline in local runtime flow.
- No API key required for core transcription path.
- Runtime config and generated files remain local unless user manually shares them.

## 13) Recommended Maintenance

- Keep Python pinned to 3.10 for compatibility.
- Keep config defaults conservative (en + base) for stable behavior.
- Add stricter validation in config loader to reject invalid language/model values.
- Add startup diagnostics log for faster field debugging.

## 14) Quick Reference

- Run app: python pisumathu.py
- Build app: pyinstaller --clean --noconfirm pisumathu.spec
- Main entry: pisumathu.py
- Main controller: core/controller.py
- ASR engine: transcription/engine.py
- UI window: ui/main_window.py
- Tray logic: ui/tray.py
- Startup registry logic: core/startup.py
- Config logic: config/settings.py

## 15) Final Note

This guide is intended as a project-level handbook for development, private deployment, and issue diagnosis.
If you expand the app, update this file along with README and DEVELOPMENT docs so the documentation stays consistent.
