# AGENTS.md — Pisumathu

Guidance for AI coding agents working in this repository.

Read this before touching code. Then read `CURRENT_STATE.md` for the
line-cited audit of what exists today.

---

## 1. What this project is

Pisumathu is a local, offline push-to-talk dictation tool.

Intended user flow:

```
talk                    # starts a background daemon, no window
hold Alt+Space          # speak
release                 # text appears in the system clipboard
Ctrl+V                  # paste anywhere
```

It is a working clone of the Wispr Flow interaction model, restricted to
the parts that can be built reliably offline and cross-platform.

**It is not** a cloud service, a note app, or a general assistant. It does
not phone home.

## 2. Current status

The rewrite is complete and the app works on Fedora GNOME Wayland.

| Area | State |
|---|---|
| Platform | Linux (Wayland and X11) and Windows |
| Hotkey | `Alt+Space`, configurable, read from `/dev/input` on Linux |
| Output | clipboard only, via `wl-copy` / `xsel` / Win32 |
| Autostart | opt-in only, never written at runtime |
| `talk` command | installed by `pyproject.toml` |
| Tests | `pytest -q` — 111 passing |

The legacy root-level modules (`controller.py`, `engine.py`, `typer.py`,
`pill.py`, and the rest) and the `transcription/` package were deleted. They
remain reachable in git history at commit `616a654`. Do not resurrect them.

## 2a. Verified end to end

Recorded on Fedora 44, GNOME 50.6, Wayland, Python 3.14:

- model download, hash verification and manifest: pass
- model load: 0.31 s; transcription of 3.4 s of speech: 0.81 s on CPU int8
- clipboard round trip through `wl-copy`: pass
- full cycle `recording → transcribing → copied`: pass
- single instance: one daemon, lock file holds the right pid
- `talk setup` frees `Alt+Space` and `--undo` restores it
- cold start: 0.96 s

Not verified on this machine: Windows, and a real physical keypress (the
edge handler is unit tested instead).

## 3. Non-negotiable product rules

These came from the user and override convenience:

1. **No autostart at OS login.** The daemon starts only when the user runs
   `talk`. There is an opt-in command, never a default.
2. **Clipboard is the output contract.** Do not add synthetic keystroke
   injection as the primary path. It is unreliable on Wayland and was
   explicitly deferred.
3. **Fully offline after model download.** No network calls at runtime.
4. **Alt+Space is the default hotkey and must be configurable.**
5. **Windows and Linux must both work.** Neither may regress to make the
   other easier.
6. **No `sudo` at runtime.** The only privilege ask is `input` group
   membership, granted once by the user.

## 4. Target layout

```
pisumathu/
  __main__.py          python -m pisumathu
  cli.py               `talk` entry point
  app.py               daemon bootstrap
  config.py            settings load/save
  state.py             AppState + orchestration
  ipc.py               single instance + control socket
  security.py          temp files, permissions, log redaction
  audio/capture.py     16 kHz mono capture
  asr/engine.py        faster-whisper wrapper
  asr/models.py        download, verify, resolve local path
  hotkey/base.py       Protocol
  hotkey/windows.py
  hotkey/linux_evdev.py
  hotkey/linux_x11.py
  output/base.py
  output/clipboard.py
  autostart/{base,windows,linux}.py
  ui/pill.py
  ui/main_window.py
  tray.py
tests/
pyproject.toml
```

## 5. Layering rules

- `state.py` orchestrates. It must not import a platform module directly;
  it talks to the `base` interfaces.
- Every OS-specific behaviour lives in exactly one adapter file, selected at
  startup. No `if sys.platform == ...` inside business logic.
- UI never imports the controller's internals. Callbacks only.
- All Tk calls happen on the main thread. Worker threads use
  `root.after(0, ...)`. This rule already exists and is correct —
  preserve it.
- One responsibility per file. If a file passes ~400 lines, it is doing
  too much.

## 6. Security invariants

Violating any of these is a bug, not a style issue.

| Rule | Why |
|---|---|
| Audio WAVs go to `$XDG_RUNTIME_DIR` / `%LOCALAPPDATA%\Temp`, mode `0600` | recorded speech is sensitive |
| Delete WAV in `finally`, always | crash must not leave audio on disk |
| `config.json` mode `0600` | may contain paths and preferences |
| Never log transcript text by default | it is the user's speech |
| No bare `except: pass` in hotkey, audio, or focus paths | silent failure is worse than a crash |
| Self-target checks fail **closed** | never type into our own window |
| Model files SHA256-verified before load | supply chain |
| Exact dependency pins | reproducibility |
| Single instance via lock file | two daemons fight over the mic |
| No outbound sockets after model download | the core promise |

## 7. Commands

```bash
# install (dev)
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# run the daemon directly
python -m pisumathu

# run the CLI
talk
talk status
talk stop

# tests
pytest -q
pytest -q tests/test_hotkey_parser.py

# lint / format
ruff check .
ruff format --check .

# type check
mypy pisumathu
```

Windows equivalents use `.venv\Scripts\activate`.

There is no CI yet. Do not claim a phase is done without running the
relevant command and pasting the output.

## 8. Testing expectations

- Pure logic (hotkey parsing, config merge, pre-roll buffer, path
  confinement) must have unit tests.
- Adapters (`hotkey/*`, `output/*`, `autostart/*`) get a fake implementation
  so `state.py` is testable without a desktop session.
- Anything requiring a real desktop is verified manually and recorded in
  the phase notes. Do not fake a manual verification.
- Every security invariant in §6 gets at least one test.

## 9. Code style

- Python 3.11+ (the docs say 3.10; treat 3.11 as the floor, do not break 3.10
  without saying so).
- Type hints on all public functions.
- Docstrings on modules, classes, and public methods.
- No global mutable state outside the app state object.
- Prefer small dataclasses over dicts for structured data.
- Errors carry a reason string that can be shown to the user.

## 10. Definition of done for the current milestone

1. `talk` launches a detached daemon, no window, tray icon only.
2. Hold Alt+Space → pill appears → speak → release.
3. Text is in the clipboard within ~2 s.
4. Ctrl+V pastes it into any GNOME Wayland app.
5. `talk stop` exits cleanly, no orphan threads.
6. Nothing starts at OS login.
7. No network traffic after `talk model download`.
8. Same flow works on Windows 11.

Anything not on this list is out of scope until this list is green.

## 11. Document map

| File | Purpose |
|---|---|
| `AGENTS.md` | this file — operating rules |
| `CURRENT_STATE.md` | line-cited audit of the code as it is today |
| `docs/superpowers/specs/2026-10-30-pisumathu-talk-design.md` | approved design |
| `docs/DEVELOPMENT.md` | **stale** — describes the pre-migration Windows app; do not trust |
| `docs/README.md` | **stale** — same |
| `README.md` | user-facing; being rewritten in Phase 7 |

When code and `CURRENT_STATE.md` disagree, the code wins and the doc gets
updated in the same change.

## 12. Known traps

- **`-transparentcolor` is Windows-only.** `ui/pill.py` applies it only on
  Windows; using it on X11 raises and leaves an opaque black rectangle.
- **Do not reintroduce PyAV decoding.** `asr/engine.py` reads the WAV itself
  and passes a float32 array. faster-whisper's file path calls
  `av.open(metadata_errors=...)`, which PyAV 16 removed.
- **Do not use `snapshot_download`.** It stalled for minutes here. Downloads
  go through the HF tree API so each file can be hash-verified.
- **IPv6 can hang downloads.** `asr/models.py` prefers IPv4 while fetching;
  without it `urlopen` blocks on a host with AAAA records but no route.
- **The tray is optional and slow.** It is attached on a background thread and
  stopped on another one; never call it on the main path.
- **Tk is main-thread only.** Worker threads push onto `Daemon._events` and
  the main loop drains it. Do not call `after()` from a worker.
- **Never write autostart at runtime.** Only `talk autostart on` may do that.
  The old build re-enabled itself on every launch, which is what made it
  reappear at login after being disabled.
- **WAV cleanup belongs in `finally`.** `state.py` deletes the file there so a
  failed transcription cannot leave recorded speech on disk.
