# Pisumathu `talk` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a working offline push-to-talk dictation daemon on Fedora GNOME Wayland and Windows 11: `talk` starts it, Alt+Space records, release puts text in the clipboard.

**Architecture:** A `pisumathu` package replaces the flat Windows-only modules. A `talk` CLI talks to a detached daemon over a Unix socket. The daemon owns a Tk main loop (pill + window), a hotkey adapter, a sounddevice recorder, and a lazy-loaded faster-whisper engine. Platform-specific behaviour lives in `hotkey/`, `output/`, and `autostart/` adapters selected at startup.

**Tech Stack:** Python 3.11+ (tested on 3.14), faster-whisper + ctranslate2, sounddevice (libportaudio), evdev / pynput, wl-copy / Win32 ctypes, Tk 9, pystray (optional).

**Spec:** `docs/superpowers/specs/2026-10-30-pisumathu-talk-design.md`

## Global Constraints

- Python floor 3.11; no `match`-only syntax that breaks 3.11.
- No autostart at OS login unless `talk autostart on` is run.
- Clipboard is the only output path. No synthetic keystrokes.
- No network after `talk model download`. `local_files_only=True` on load.
- Default model `tiny`, compute type `int8`.
- Inference: `beam_size=1`, `best_of=1`, `vad_filter=True`, `num_workers=1`, `cpu_threads=2`.
- Idle unload after 300 s.
- Audio WAVs in `$XDG_RUNTIME_DIR/pisumathu`, mode `0600`, deleted in `finally`.
- `config.json` mode `0600`.
- Never log transcript text unless `--verbose`.
- No bare `except: pass` in hotkey, audio, or output paths.
- All Tk calls on the main thread; workers use `root.after(0, ...)`.
- `state.py` never imports a platform adapter directly.

## Review Focus

- **Hotkey parser fed garbage** (`""`, `"alt+"`, `"ctrl+banana"`, `"alt+alt"`) must raise a clear `ValueError`, not crash the daemon at startup.
- **Recorder stopped without ever starting**, and **started twice**, must be idempotent and never leak a stream.
- **Transcription on a silent/empty WAV** must return `None` and emit `ERROR`, never paste `""` or hang.
- **Clipboard backend absent** (`wl-copy` missing, no display) must return `False` and surface `ERROR`, not raise.
- **Config file corrupted or missing** must fall back to defaults and keep working, not abort startup.
- **Two `talk` invocations at once** must yield exactly one daemon; the second prints status and exits `0`.
- **Daemon killed mid-recording** must not leave a WAV in `$XDG_RUNTIME_DIR`.

---

### Task 1: Package skeleton, paths, security primitives

**Files:**
- Create: `pyproject.toml`, `pisumathu/__init__.py`, `pisumathu/paths.py`, `pisumathu/security.py`
- Test: `tests/test_paths.py`, `tests/test_security.py`

**Interfaces:**
- Produces: `paths.app_data_dir() -> Path`, `paths.runtime_dir() -> Path`, `paths.config_path() -> Path`, `paths.log_path() -> Path`, `paths.models_dir() -> Path`, `paths.lock_path() -> Path`, `paths.socket_path() -> Path`
- Produces: `security.secure_audio_path() -> Path` (0600, in runtime dir), `security.ensure_private(path: Path) -> None`, `security.redact(text: str) -> str`

- [ ] **Step 1:** Write `tests/test_paths.py` asserting `runtime_dir()` exists with mode `0o700` and `config_path()` is under `app_data_dir()`.
- [ ] **Step 2:** Run it; expect `ModuleNotFoundError`.
- [ ] **Step 3:** Implement `paths.py` and `security.py`.
- [ ] **Step 4:** Run `pytest tests/test_paths.py tests/test_security.py -v`; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 2: Config with atomic private writes

**Files:**
- Create: `pisumathu/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `config.Config` dataclass with `hotkey: str`, `model: str`, `device: str`, `compute_type: str`, `language: str | None`, `beam_size: int`, `vad_filter: bool`, `clipboard_auto_clear_seconds: int`, `idle_unload_seconds: int`, `show_pill: bool`, `autostart: bool`, `verbose: bool`
- Produces: `config.load_config(path: Path | None = None) -> Config`, `config.save_config(cfg: Config, path: Path | None = None) -> None`

- [ ] **Step 1:** Tests: missing file → defaults; corrupt JSON → defaults; unknown keys ignored; saved file is mode `0600`; round-trip preserves values.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement with atomic `tmp + os.replace`.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 3: Hotkey parser

**Files:**
- Create: `pisumathu/hotkey/__init__.py`, `pisumathu/hotkey/parser.py`
- Test: `tests/test_hotkey_parser.py`

**Interfaces:**
- Produces: `parser.HotkeySpec(keys: frozenset[str], raw: str)`, `parser.parse_hotkey(text: str) -> HotkeySpec`, `parser.format_hotkey(spec: HotkeySpec) -> str`, `parser.KEY_ALIASES: dict[str, str]`

- [ ] **Step 1:** Tests: `"alt+space"` → `{"alt","space"}`; whitespace and case tolerated; `"ctrl+banana"` raises `ValueError`; `""` raises; `"alt+"` raises; `"alt+alt"` collapses to one key; `format_hotkey(parse("ALT + Space")) == "Alt+Space"`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement canonical name table covering modifiers, `space`, `enter`, `tab`, `esc`, `backspace`, `delete`, `f1`–`f12`, `a`–`z`, `0`–`9`, arrows.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 4: Pre-roll buffer and recorder

**Files:**
- Create: `pisumathu/audio/__init__.py`, `pisumathu/audio/buffer.py`, `pisumathu/audio/capture.py`
- Test: `tests/test_buffer.py`

**Interfaces:**
- Produces: `buffer.PreRollBuffer(capacity_chunks: int)` with `.push(chunk)`, `.drain() -> list`, `.__len__`
- Produces: `capture.Recorder` with `.start_listener()`, `.start() -> None`, `.stop() -> Path`, `.stop_listener()`, `.is_recording -> bool`, `.error -> str | None`

- [ ] **Step 1:** Tests for `PreRollBuffer`: bounded capacity, FIFO eviction, drain empties.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement buffer and recorder (sounddevice `InputStream`, 16 kHz mono int16, 1024 frames, 200 ms pre-roll, `wave` writer to `security.secure_audio_path()`).
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 5: ASR engine and model manager

**Files:**
- Create: `pisumathu/asr/__init__.py`, `pisumathu/asr/engine.py`, `pisumathu/asr/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces: `models.MODEL_IDS: dict[str, str]` (name → HF repo), `models.resolve_model(name: str) -> Path`, `models.download_model(name: str, progress=None) -> Path`, `models.model_available(name: str) -> bool`
- Produces: `engine.TranscriptionEngine(model_path: Path, device: str, compute_type: str, language: str | None, ...)` with `.load()`, `.unload()`, `.is_loaded`, `.transcribe(wav: Path) -> str | None`

- [ ] **Step 1:** Tests: `resolve_model` rejects `..` and unknown names; returns a path under `models_dir()`; `model_available` is `False` on an empty dir.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement. Download pins the HF revision recorded in a local `manifest.json`; load verifies file hashes from that manifest and passes `local_files_only=True`.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 6: Hotkey adapters

**Files:**
- Create: `pisumathu/hotkey/base.py`, `pisumathu/hotkey/linux_evdev.py`, `pisumathu/hotkey/linux_x11.py`, `pisumathu/hotkey/windows.py`, `pisumathu/hotkey/factory.py`
- Test: `tests/test_hotkey_factory.py`

**Interfaces:**
- Produces: `base.HotkeyBackend` protocol: `.start(on_press, on_release)`, `.stop()`, `.name: str`
- Produces: `factory.create_hotkey(spec: HotkeySpec) -> HotkeyBackend`

- [ ] **Step 1:** Test that `create_hotkey` returns an object with `name`, `start`, `stop`, and that `FakeBackend` satisfies the protocol.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement evdev backend (device scan every 2 s, per-device `select` loop, no `EVIOCGRAB`), pynput fallbacks, and factory.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 7: Clipboard output and autostart

**Files:**
- Create: `pisumathu/output/__init__.py`, `pisumathu/output/base.py`, `pisumathu/output/clipboard.py`, `pisumathu/autostart/__init__.py`, `pisumathu/autostart/base.py`, `pisumathu/autostart/linux.py`, `pisumathu/autostart/windows.py`
- Test: `tests/test_clipboard.py`, `tests/test_autostart.py`

**Interfaces:**
- Produces: `clipboard.Clipboard` with `.copy(text: str) -> bool`, `.backend: str`
- Produces: `autostart.get_autostart() -> Autostart` with `.is_enabled() -> bool`, `.enable() -> None`, `.disable() -> None`

- [ ] **Step 1:** Tests: `Clipboard().copy("")` returns `False`; a fake backend returning `False` propagates; Linux autostart writes a `.desktop` file under a temp `XDG_CONFIG_HOME` and `disable()` removes it.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement `wl-copy` → GTK4 → `xsel` chain on Linux, Win32 on Windows, and XDG `.desktop` / HKCU `Run` autostart.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 8: State machine

**Files:**
- Create: `pisumathu/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `state.AppState` enum: `LOADING, IDLE, RECORDING, TRANSCRIBING, COPIED, ERROR, UNAVAILABLE`
- Produces: `state.DictationService(recorder, engine, clipboard, on_state, on_transcript)` with `.press()`, `.release()`, `.shutdown()`

- [ ] **Step 1:** Tests with fakes: press→`RECORDING`; release→`TRANSCRIBING`→`COPIED`→`IDLE`; clipboard failure→`ERROR`; empty transcript→`ERROR`; press while `TRANSCRIBING` is ignored; WAV deleted after transcription including on exception.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement with a lock, a worker thread, and `try/finally` cleanup.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 9: IPC, single instance, daemon

**Files:**
- Create: `pisumathu/ipc.py`, `pisumathu/daemon.py`, `pisumathu/app.py`
- Test: `tests/test_ipc.py`

**Interfaces:**
- Produces: `ipc.DaemonLock(path)` with `.acquire() -> bool`, `.release()`
- Produces: `ipc.ControlServer(path)` with `.start()`, `.stop()`; `ipc.send(command: str, path: Path, timeout: float = 2.0) -> dict`
- Produces: `app.run_daemon() -> int`

- [ ] **Step 1:** Tests: second `acquire()` on the same lock returns `False`; `send` to a missing socket raises `DaemonNotRunning`.
- [ ] **Step 2:** Run; expect failure.
- [ ] **Step 3:** Implement AF_UNIX on POSIX, TCP+token on Windows, JSON line protocol.
- [ ] **Step 4:** Run; expect PASS.
- [ ] **Step 5:** Commit.

---

### Task 10: Pill, main window, tray

**Files:**
- Create: `pisumathu/ui/__init__.py`, `pisumathu/ui/pill.py`, `pisumathu/ui/main_window.py`, `pisumathu/tray.py`

**Interfaces:**
- Produces: `pill.PillOverlay(root: tk.Tk, on_copy_last, on_clear)` with `.set_state(AppState, detail: str = "")`, `.destroy()`
- Produces: `main_window.MainWindow(root, config, on_change_hotkey, on_quit, on_hide)` with `.set_state`, `.append_transcript`, `.set_model`
- Produces: `tray.Tray(on_show, on_quit)` with `.start()`, `.stop()`; failure is non-fatal

- [ ] **Step 1:** Implement pill with `-transparentcolor` guarded to Windows, `-alpha 0.94`, hidden when `IDLE`.
- [ ] **Step 2:** Implement window per spec §8 with ≥4.5:1 contrast and no START/STOP or STARTUP sections.
- [ ] **Step 3:** Implement tray with a try/except that logs and continues.
- [ ] **Step 4:** Manual check: `python -m pisumathu.daemon` shows no window.
- [ ] **Step 5:** Commit.

---

### Task 11: CLI and setup

**Files:**
- Create: `pisumathu/cli.py`, `pisumathu/__main__.py`
- Modify: `pyproject.toml` (console script `talk`)

**Interfaces:**
- Produces: `cli.main(argv: list[str] | None = None) -> int` with subcommands `status`, `stop`, `setup`, `config`, `model download`, `autostart on|off`, `logs`, `version`.

- [ ] **Step 1:** Implement argparse dispatch; bare `talk` starts the daemon if absent else prints status.
- [ ] **Step 2:** `talk setup` reads the current `activate-window-menu`, stores it in config for `--undo`, and sets it to `[]`.
- [ ] **Step 3:** Run `talk --help`, `talk status`, `talk version`.
- [ ] **Step 4:** Commit.

---

### Task 12: Delete legacy duplicates, rewrite docs, end-to-end test

**Files:**
- Delete: `controller.py`, `engine.py`, `engine_cpu.py`, `capture.py`, `settings.py`, `typer.py`, `main_window.py`, `pill.py`, `transcription/`
- Modify: `README.md`, `.gitignore`
- Test: full manual run

- [ ] **Step 1:** `git add core/engine.py core/audio_buffer.py` before deleting anything.
- [ ] **Step 2:** Delete legacy modules and the old `core/`, `audio/`, `ui/`, `config/` trees after the new package passes tests.
- [ ] **Step 3:** Run the full suite.
- [ ] **Step 4:** End-to-end: `talk` → hold Alt+Space → speak → release → `wl-paste` shows the text.
- [ ] **Step 5:** Commit.
