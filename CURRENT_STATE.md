# Pisumathu — Current State

> **Historical document.** This is the audit of the code *before* the rewrite.
> The migration it recommended is complete: the `pisumathu/` package replaced
> every module described below, and the legacy files it lists under §1.2 and
> §5.3 have been deleted. Read it for the reasoning, not for the current
> layout. `AGENTS.md` describes how the code is organised now.

Reverse-audit of the codebase as it exists in the working tree.
Every claim cites `file:line`. Anything that could not be determined from
code is marked **UNKNOWN** with the missing evidence listed.

Audit date: 2026-10-30
Last commit: `4bb2764` — "UI: Adjust layout dimensions to 720px height for better control visibility"

---

## 0. Working tree state

```
 M audio/capture.py
 M config/settings.py
 M core/controller.py
 M core/startup.py
 M pisumathu.py
 M pisumathu.spec
 M ui/main_window.py
 M ui/tray.py
?? build.log
?? core/audio_buffer.py
?? core/engine.py
?? docs/README.md
```

Two files the application cannot start without are **untracked**:

- `core/engine.py` — imported by `core/controller.py:14`
- `core/audio_buffer.py` — imported by `audio/capture.py:10`

A fresh clone of `4bb2764` fails at import time with `ModuleNotFoundError`.

---

## 1. Inventory

### 1.1 Active source modules

Resolved from `pisumathu.py` downward.

| File | Responsibility | Entered from |
|---|---|---|
| `pisumathu.py` | Tk bootstrap, DI wiring, tray lifecycle, shutdown | `__main__` |
| `config/settings.py` | `config.json` load/save, `AppConfig` dataclass | `pisumathu.py:18` |
| `core/controller.py` | State machine, hotkey listener, orchestration | `pisumathu.py:19` |
| `core/engine.py` | faster-whisper inference backend | `core/controller.py:14` |
| `core/audio_buffer.py` | 200 ms pre-roll ring buffer | `audio/capture.py:10` |
| `core/typer.py` | Win32 focus capture/restore + synthetic typing | `core/controller.py:16` |
| `core/startup.py` | Windows HKCU `Run` key autostart | `pisumathu.py:20` |
| `audio/capture.py` | PyAudio listener, pre-roll, WAV serialisation | `core/controller.py:13` |
| `ui/main_window.py` | Tk control panel | `pisumathu.py:21` |
| `ui/pill.py` | Floating overlay, 4 render states | `pisumathu.py:22` |
| `ui/tray.py` | pystray icon and menu | `pisumathu.py:23` |

### 1.2 Duplicate / legacy modules (not reachable from the entry point)

| File | Note |
|---|---|
| `controller.py` | Older controller; imports `transcription.engine` (`controller.py:14`) |
| `engine.py` | Older OpenAI Whisper + PyTorch backend |
| `engine_cpu.py` | Older faster-whisper CPU backend |
| `capture.py` | Older one-shot PyAudio capture |
| `settings.py` | Older settings module, no tray/startup fields |
| `typer.py` | Older Win32 typer, uses `ShowWindow` (`typer.py:43`) |
| `main_window.py` | Older UI, 420×620 (`main_window.py:78`) |
| `pill.py` | Older pill, 170/320/220 px widths (`pill.py:33-35`) |
| `transcription/` | Package used only by the legacy duplicates |

These are shadow copies with divergent behaviour. `typer.py:35-48` and
`core/typer.py:35-69` implement focus restoration differently. Editing the
wrong one has no effect at runtime.

### 1.3 Dependency and build files

| File | Content |
|---|---|
| `requirements-cpu.txt` | `faster-whisper`, `pyaudio`, `pynput`, `pystray`, `Pillow` — all `>=` (`:8-12`) |
| `requirements-gpu.txt` | `openai-whisper`, `pyaudio`, `pynput`, `pystray`, `Pillow` (`:10-14`) |
| `pisumathu.spec` | PyInstaller onedir, `console=False` (`:36`), heavy hiddenimports (`:6`) |

No `pyproject.toml`, no lockfile, no test directory, no CI configuration.

### 1.4 Runtime paths

| Item | Value | Evidence |
|---|---|---|
| Config file | `<repo>/config.json` | `config/settings.py:12` |
| Temp audio | OS temp dir, `pisumathu_*.wav` | `audio/capture.py:185` |
| Model cache | not configured by application code | **UNKNOWN** |

**UNKNOWN — model cache location.** `core/engine.py:59-65` passes a model
identifier to `WhisperModel(...)` and never sets `download_root`,
`local_files_only`, or `HF_HOME`. The resolved cache path depends on the
installed `huggingface_hub` version and environment at runtime. Missing
evidence: a runtime trace of the first model load.

### 1.5 Python and OS assumptions

| Claim | Evidence |
|---|---|
| Python 3.10 documented | `requirements-cpu.txt:2`, `requirements-gpu.txt:2`, `README.md:43-44` |
| Host interpreter is 3.14.8 | `python --version` in this workspace |
| Windows is the only supported OS | `core/startup.py:13-16`, `core/typer.py:26-84`, `pisumathu.py:82-84`, `README.md:5` |
| CUDA optional, CPU fallback exists | `core/engine.py:162-172` |
| Repo contains a Windows venv | `whisper-env/pyvenv.cfg`, `whisper-env/Scripts/*.exe` |

---

## 2. Architecture

```
                    pisumathu.py
                         │
        ┌────────────────┼─────────────────┐
        │                │                 │
   MainWindow        TrayManager      AppController
   (Tk, main        (pystray,          (owns state)
    thread)          daemon thread)          │
        │                                    │
        │                    ┌───────────────┼───────────────┐
        │                    │               │               │
        │             TranscriptionEngine  AudioCapture    Typer
        │             (faster-whisper)     (PyAudio)      (Win32)
        │                    │               │               │
        │                    │        PreRollBuffer          │
        │                    │         (200 ms)              │
        │                    │               │               │
        │                    │          temp WAV ────────────┘
        │                    │
        └──── root.after() ──┴── callbacks from worker threads

   PillOverlay (Tk Toplevel) — created on START, destroyed on STOP
```

Thread inventory:

| Thread | Created at | Daemon | Joined on shutdown |
|---|---|---|---|
| Tk main | `pisumathu.py:30` | n/a | `root.destroy()` |
| Tray icon | `ui/tray.py:52` | yes | no |
| Model load | `core/controller.py:77` | yes | no |
| Audio listener | `audio/capture.py:73` | yes | no |
| Recording timer | `core/controller.py:210` | yes | no |
| Stop + transcribe | `core/controller.py:168` | yes | no |
| Pill animation | `ui/pill.py:117` | yes | no |
| pynput hotkey | `core/controller.py:138` | internal | yes (`:146-151`) |

Six of eight threads are never joined.

---

## 3. Exact activation sequence

### 3.1 Process start

1. `main()` parses `--tray` (`pisumathu.py:219-222`).
2. `PisumathuApp.__init__` creates `tk.Tk()` and withdraws it (`:30-32`).
3. `ConfigManager()` is constructed; no load yet (`:35`).
4. `AppController` loads config and builds subsystems (`:38`, `core/controller.py:35-46`).
5. `is_startup_enabled()` overwrites `config.start_with_windows` (`:39`).
6. `MainWindow` is built (`:42-53`).
7. `TrayManager` is constructed, then started (`:55-59`, `:70`).
8. Window shown unless tray mode (`:72-77`).
9. Own HWND captured via `GetForegroundWindow()` (`:79-86`).
10. `controller.start()` spawns the model-load thread (`:88`, `core/controller.py:75-78`).
11. `main()` re-writes the startup registry entry if config says enabled (`:226-227`).

### 3.2 Model load

1. State → `LOADING` (`core/controller.py:93`).
2. `TranscriptionEngine.load()` imports `faster_whisper` (`core/engine.py:50`).
3. Device resolution (`core/engine.py:52`, `:162-172`):
   - requested `cuda` and `torch.cuda.is_available()` → `cuda` / `int8_float16`
   - otherwise → `cpu` / `int8`
4. `WhisperModel(...)` constructed (`core/engine.py:59-65`).
5. Warm start: 1 s of silence transcribed (`core/engine.py:174-195`).
6. On success → audio listener starts, state → `IDLE`, hotkey listener starts (`core/controller.py:94-98`).
7. On failure → state → `ERROR` (`core/controller.py:99-100`). No retry, no user-visible cause.

### 3.3 Hotkey press → release

Registered in `core/controller.py:106-141` with `pynput.keyboard.Listener`.

Trigger: **`Ctrl_L` and `Ctrl_R` held simultaneously.** Not Alt+Space.

```
press  Ctrl_L  → _left_ctrl  = True
press  Ctrl_R  → _right_ctrl = True
                 both true and not _hotkey_active
                 → _hotkey_active = True
                 → Typer.capture_focus()          core/controller.py:160
                 → AudioCapture.start()           core/controller.py:175
                 → state = RECORDING              core/controller.py:177
                 → timer thread starts            core/controller.py:178

release Ctrl_L or Ctrl_R
                 → _hotkey_active = False
                 → spawn _stop_and_transcribe     core/controller.py:168
```

Notes:

- Only left/right Ctrl are recognised. Alt and Space are never inspected.
- Pressing either Ctrl alone does nothing.
- The combination is hardcoded; `AppConfig` has no hotkey field (`config/settings.py:30-39`).
- `on_press`/`on_release` wrap everything in `except Exception: pass` (`:119-120`, `:134-135`).

### 3.4 Audio capture

| Parameter | Value | Evidence |
|---|---|---|
| Library | PyAudio | `audio/capture.py:13` |
| Sample rate | 16 000 Hz | `:19` |
| Channels | 1 (mono) | `:20` |
| Format | `paInt16` | `:133` |
| Chunk | 1024 frames ≈ 64 ms | `:21` |
| Pre-roll | 200 ms | `:49`, `core/audio_buffer.py:24-27` |
| Temp file | `tempfile.mkstemp(prefix="pisumathu_", suffix=".wav")` | `:185` |

Flow: listener thread opens a stream once (`:125-143`); idle chunks feed the
pre-roll deque (`:153`); `start()` drains pre-roll into `_frames` (`:95-97`);
recording chunks append (`:148-149`); `stop()` writes the WAV (`:105-112`).

### 3.5 Inference

```python
segments, _ = self._model.transcribe(
    wav_path,
    language="en",                 # hardcoded
    beam_size=5,
    best_of=5,
    temperature=0.0,
    condition_on_previous_text=False,
    vad_filter=False,
    word_timestamps=False,
    no_speech_threshold=0.3,
    compression_ratio_threshold=2.4,
)
```

`core/engine.py:105-116`.

Model construction: `num_workers=2`, `cpu_threads=4` (`core/engine.py:63-64`).

Default model size is inconsistent across three places:

| Source | Value |
|---|---|
| `config/settings.py:21` `DEFAULT_CONFIG` | `large-v3-turbo` |
| `config/settings.py:35` dataclass default | `base` |
| `config/settings.py:77` load fallback | `base` |
| `ui/main_window.py:178` badge (hardcoded string) | `large-v3-turbo` |

With no `config.json` present, `ConfigManager.load()` returns `AppConfig()`,
so the effective default is **`base`**, while the UI advertises
`large-v3-turbo`.

### 3.6 Output delivery

Two independent sinks, both always executed:

1. **Chatbox.** `on_transcript` → `MainWindow.append_transcript` (`core/controller.py:191-192`, `ui/main_window.py:409-415`).
2. **Synthetic typing into the captured window** (`core/controller.py:194`).

Typing sequence (`core/typer.py:141-181`):

1. Return `False` if `_enabled` is false.
2. Return `False` if no HWND captured.
3. Return `False` if target HWND belongs to this process (`:160`).
4. `_restore_focus(hwnd)` (`:165`): `AllowSetForegroundWindow`, `AttachThreadInput`, `BringWindowToTop`, `SetForegroundWindow` (`:52-64`).
5. `time.sleep(0.15)` (`:171`).
6. `pynput.keyboard.Controller().type(text)` (`:175-176`).

There is **no clipboard interaction anywhere in the codebase.** No
`pyperclip`, no `xclip`, no `wl-copy`, no `Gdk.Clipboard`, no Win32
clipboard API. Verified by repository-wide search.

### 3.7 Pill lifecycle

- Created only by the START button (`pisumathu.py:94-97`, `ui/main_window.py:452-456`).
- Destroyed by STOP (`pisumathu.py:99-102`) or shutdown (`:177`).
- Before START is pressed, the hotkey still records and transcribes, but
  nothing is displayed.

### 3.8 Shutdown

`_shutdown()` (`pisumathu.py:173-180`): destroy pill → `controller.stop()` →
`tray.stop()` → `root.destroy()`.

`controller.stop()` (`core/controller.py:80-87`): stop hotkey listener →
`audio.stop()` only if state is `RECORDING` → `audio.stop_listener()` →
save config.

Not stopped: model-load thread, in-flight transcription, timer thread,
listener thread, pill animation thread.

---

## 4. Current limitations

### 4.1 Platform

| Gap | Evidence |
|---|---|
| Hotkey uses `pynput`, X11-only on Linux | `core/controller.py:108` |
| Focus capture/restore is Win32-only | `core/typer.py:26-84` |
| Autostart is `winreg`-only | `core/startup.py:13-16` |
| Overlay transparency is a Windows-only Tk attribute | `ui/pill.py:98` |
| Tray untested on Linux | `ui/tray.py:1-77` |
| No Linux install path in docs | `README.md:38-93` |

`wm attributes -transparentcolor` is not implemented by Tk on X11 or
Wayland. On Linux the pill renders as an opaque `#010101` rectangle.
**Verify on target hardware** — this is inferred from Tk's documented
attribute set, not observed on a Linux run.

### 4.2 Correctness bugs

| # | Bug | Evidence |
|---|---|---|
| 1 | Configured language is ignored; inference hardcodes `"en"` | `core/engine.py:106` |
| 2 | Engine constructed with `language="en"` regardless of config | `core/controller.py:44` |
| 3 | Language UI removed but wiring still present | `ui/main_window.py:299`, `pisumathu.py:48`, `:147-150` |
| 4 | Model badge is a hardcoded string | `ui/main_window.py:178` |
| 5 | Default model differs between dataclass and `DEFAULT_CONFIG` | `config/settings.py:21` vs `:35` |
| 6 | `AppState.ERROR` has no pill render branch | `ui/pill.py:180-277` |
| 7 | Recording colour semantics inverted (red idle, green recording) | `ui/pill.py:201`, `:222` |
| 8 | No success feedback after transcription | no `COPIED` state exists |
| 9 | Dead model-switch path (`MODEL_OPTIONS = []`) | `ui/main_window.py:20`, `core/controller.py:247-288` |
| 10 | `pad` dict built and never used | `ui/main_window.py:161` |
| 11 | Status text says "check console"; build has `console=False` | `ui/main_window.py:434`, `pisumathu.spec:36` |
| 12 | Startup label is Windows-specific on a cross-platform app | `ui/main_window.py:357` |

### 4.3 Resource

| Hotspot | Evidence |
|---|---|
| `large-v3-turbo` resident | `config/settings.py:21` |
| 2 workers, 4 CPU threads | `core/engine.py:63-64` |
| `beam_size=5`, `best_of=5` | `core/engine.py:108-109` |
| VAD disabled → full-clip decode | `core/engine.py:112` |
| Always-open microphone stream | `audio/capture.py:125-143` |
| Two 25 FPS loops (Tk redraw + animation thread) | `ui/pill.py:178`, `:167` |
| Model never unloaded | no eviction path exists |
| GPU bundle ≈ 2.3 GB | `docs/DEVELOPMENT.md:310` |

No RSS or CPU measurement exists in the repository. Target `<80 MB` is
**UNKNOWN / unverified** and implausible for Python + faster-whisper with a
model resident.

### 4.4 Security

| # | Issue | Evidence | Impact |
|---|---|---|---|
| S1 | Autostart re-written on every launch | `pisumathu.py:226-227` | user cannot permanently disable autostart |
| S2 | Speech WAV in shared temp dir, default permissions | `audio/capture.py:185-191` | other local users may read recorded speech on multi-user systems |
| S3 | WAV leaked if transcription raises | `core/controller.py:185-187` | audio persists on disk |
| S4 | Own-window check fails open | `core/typer.py:72-84` | text may be typed into Pisumathu itself |
| S5 | All hotkey/focus errors swallowed | `core/controller.py:119-120`, `:134-135`, `core/typer.py:31`, `:83` | silent failure, no diagnostics |
| S6 | Transcript preview printed to stdout | `core/engine.py:121-122` | speech content in terminal scrollback / journald |
| S7 | Model downloaded with no integrity verification | `core/engine.py:59-65` | supply-chain risk on first run |
| S8 | Dependencies unpinned (`>=`) | `requirements-cpu.txt:8-12` | non-reproducible, vulnerable to upstream compromise |
| S9 | No single-instance guard | none | two daemons compete for mic and hotkey |
| S10 | Config written with default umask | `config/settings.py:92-93` | world-readable settings |
| S11 | No clipboard retention policy | no clipboard code exists | n/a today; becomes relevant once clipboard is added |
| S12 | Synthetic keystrokes race focus changes | `core/typer.py:165-176` | text can land in the wrong application |

---

## 5. Files that must change

### 5.1 Rewrite

| File | Reason |
|---|---|
| `core/controller.py` | hotkey abstraction, `COPIED` state, clipboard output, joined threads |
| `core/typer.py` | replace with platform `output/` package; clipboard is primary |
| `core/startup.py` | cross-platform; remove runtime self-heal |
| `audio/capture.py` | secure temp dir, `0600`, joined listener, `try/finally` |
| `ui/pill.py` | new state machine, Linux-safe transparency, hidden-when-idle |
| `ui/main_window.py` | remove STARTUP/START-STOP, add hotkey + clipboard, fix contrast |
| `pisumathu.py` | daemon bootstrap, no GUI on start, IPC, single instance |
| `config/settings.py` | hotkey, clipboard, model path, resolved defaults, `0600` |
| `README.md` | dual-platform install |

### 5.2 Add

```
pyproject.toml
AGENTS.md
CURRENT_STATE.md
pisumathu/__main__.py
pisumathu/cli.py
pisumathu/ipc.py
pisumathu/security.py
pisumathu/hotkey/{base,windows,linux_evdev,linux_x11}.py
pisumathu/output/{base,clipboard,inject_windows,inject_linux}.py
pisumathu/asr/models.py
tests/
```

### 5.3 Delete

```
controller.py
engine.py
engine_cpu.py
capture.py
settings.py
typer.py
main_window.py
pill.py
transcription/
```

### 5.4 Git actions

- `git add core/engine.py core/audio_buffer.py` — currently untracked and required.
- Add `build.log`, `dist/`, `whisper-env/` to `.gitignore` verification (already covered at `.gitignore:8`, `:13`; `build.log` is not).

---

## 6. Unresolved / UNKNOWN

| Item | Missing evidence |
|---|---|
| Model cache directory at runtime | no `download_root` set; needs runtime trace |
| Actual idle RSS and CPU | no measurement in repo; needs profiling on both platforms |
| Whether CUDA is present on the user's machine | environment-specific |
| GNOME version and portal `GlobalShortcuts` availability | environment-specific |
| Whether `input` group membership is configured | environment-specific |
| Whether `-transparentcolor` failure on Linux manifests as opaque black | inferred from Tk docs; needs a Linux run |
| Behaviour of `pystray` on GNOME Wayland | untested |
| Whether `pynput` can read keys under Wayland at all | untested |
