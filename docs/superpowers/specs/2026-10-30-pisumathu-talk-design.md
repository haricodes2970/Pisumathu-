# Pisumathu `talk` — Design

Status: approved in conversation, pending written-spec review
Date: 2026-10-30
Supersedes: the Windows-only, Ctrl-hotkey, type-into-window model

---

## 1. Purpose

Turn Pisumathu into a local, offline push-to-talk dictation tool for
**Windows and Linux/Fedora**, driven by a single `talk` command.

Success is defined narrowly for this milestone:

> Run `talk`. Hold Alt+Space. Speak. Release. The transcribed text is in the
> system clipboard. Press Ctrl+V anywhere.

No other behaviour is required to ship this milestone.

## 2. Scope

### In scope

- `talk` CLI: install once, launch a background daemon
- Alt+Space hold-to-talk, configurable
- Offline local ASR via faster-whisper
- Clipboard output
- Floating pill overlay with recording / transcribing / copied / error states
- Improved main window
- Windows and Fedora GNOME Wayland support
- Security fixes S1–S12 from `CURRENT_STATE.md`

### Out of scope (deliberately deferred)

- Streaming / partial transcription
- Auto-paste into the focused application
- LLM rewrite, tone, command mode
- History search, sync, accounts
- GNOME Shell extension for a pixel-perfect overlay
- Rust / whisper.cpp core
- Autostart at OS login (explicitly rejected by the user)
- macOS

## 3. Confirmed constraints

| Constraint | Consequence |
|---|---|
| Target desktop is GNOME on Wayland | no layer-shell, no synthetic input, no global key grab |
| Clipboard is the output contract | no focus restoration required |
| No OS-login autostart | `talk` is the only entry point |
| Idle memory matters | model must unload when idle |
| Windows must keep working | all OS-specific code sits behind interfaces |

### 3.1 Why clipboard-first

Wayland provides no synthetic-input API for arbitrary clients:

| Tool | Works on |
|---|---|
| `xdotool` | X11 only |
| `pynput` | X11 only on Linux |
| `wtype` | wlroots only (sway, Hyprland) — **not Mutter** |
| `ydotool` | needs a privileged `ydotoold` + uinput |
| AT-SPI | unreliable for real keystrokes |

Clipboard works everywhere. Making it the contract removes an entire class
of platform-specific failure and matches the stated requirement.

### 3.2 Why Alt+Space needs setup

Mutter owns `Alt+Space` via
`org.gnome.desktop.wm.keybindings activate-window-menu`.
Linux input grabbing is per-device (`EVIOCGRAB`), so suppressing one
combination would block the entire keyboard. Therefore:

- `talk setup` sets `activate-window-menu` to `[]` with explicit user consent.
- `talk setup --undo` restores the original value.
- The hotkey remains configurable; Alt+Space is only the default.

### 3.3 Why the pill is an XWayland window

`wlr-layer-shell` is not implemented by Mutter. A true always-on-top
borderless window is only achievable through a GNOME Shell extension.
Milestone decision: XWayland override-redirect window, exact pill bounds,
whole-window `-alpha`. Corner tint is accepted. Extension deferred.

## 4. Architecture

```
talk ──► cli.py ──► ipc.py ──► app.py (daemon)
                                  │
      ┌───────────┬───────────────┼──────────────┬─────────────┐
      │           │               │              │             │
  hotkey/      audio/           asr/         output/        ui/
  base.py      capture.py       engine.py    clipboard.py   pill.py
   ├ windows    (16 kHz mono)    models.py    inject_*.py    main_window.py
   ├ linux_evdev                                (deferred)   tray.py
   └ linux_x11

  autostart/  security.py  config.py  state.py
```

Layering rule: nothing above the adapter layer may import a platform
module directly. `state.py` depends only on interfaces.

### 4.1 Component contracts

| Component | Input | Output | Depends on |
|---|---|---|---|
| `cli` | argv | exit code, human text | `ipc` |
| `ipc` | command | `Status` | lock file, socket |
| `hotkey` | — | `on_press()`, `on_release()` | OS input |
| `audio` | start/stop | WAV path | PyAudio |
| `asr` | WAV path | text or `None` | faster-whisper |
| `models` | model id | verified local path | filesystem |
| `output/clipboard` | text | success bool | Gdk / Win32 |
| `state` | events | `AppState` transitions | all interfaces |
| `ui/pill` | state | pixels | Tk |
| `ui/main_window` | state, config | user intent | Tk |

Each component is independently testable. `hotkey`, `output`, and
`autostart` each have a `base` interface plus one implementation per OS.

## 5. Hotkey subsystem

```
hotkey/base.py       Protocol: start(on_press, on_release), stop()
hotkey/windows.py    pynput.keyboard.Listener
hotkey/linux_evdev.py  /dev/input/event*, requires `input` group
hotkey/linux_x11.py    pynput fallback when evdev is unavailable
```

- Combination parsed from config string, default `alt+space`.
- Hold-to-talk: fire `on_press` on the completing key-down, `on_release`
  when any member key goes up.
- Debounce: ignore a new press until the previous cycle reached `IDLE`.
- evdev: enumerate devices via `/dev/input/by-id`, re-scan every 2 s for
  hotplug, no `EVIOCGRAB`.
- If no backend initialises, daemon stays alive and `talk status` reports
  `hotkey: unavailable` with the reason.

## 6. Clipboard subsystem

```
output/clipboard.py
  Linux   → Gdk.Clipboard.set(text)        (Wayland-native, no subprocess)
  Windows → Win32 OpenClipboard/SetClipboardData via ctypes
```

- Returns success boolean; failure surfaces as pill `ERROR`.
- Optional auto-clear after N seconds, default off.
- `inject_*.py` exists as an interface stub only; no implementation this milestone.

## 7. Pill state machine

```
        ┌──────────────────────────────────────┐
        │                                      │
     IDLE ──hotkey down──► RECORDING ──up──► TRANSCRIBING
        ▲                                      │
        │                            ┌─────────┴─────────┐
        │                            ▼                   ▼
        │                         COPIED              ERROR
        │                            │                   │
        └──────── 1.2 s ─────────────┘                   │
        └────────────────── 3 s ─────────────────────────┘
```

| State | Size | Content | Visible |
|---|---|---|---|
| IDLE | — | — | hidden |
| LOADING | 40×18 | muted capsule | yes |
| RECORDING | ~120×28 | red blinking dot, 8 bars, timer | yes |
| TRANSCRIBING | ~110×26 | spinner | yes |
| COPIED | ~80×26 | ✓ Copied | 1.2 s |
| ERROR | ~140×26 | ! + short reason | 3 s |

Rules:

- Created at daemon start; never gated behind a button.
- Red means recording. Green check means success. Conventional mapping.
- ERROR must always be renderable — never silent.
- Rendering is Tk `after()` only, no background animation thread.
- Linux: `overrideredirect(True)`, `-topmost`, `-alpha 0.94`, window sized
  exactly to the pill. `-transparentcolor` is Windows-only and must be
  applied conditionally.

## 8. Main window

Layout:

```
┌────────────────────────────────────────────┐
│ ◈ PISUMATHU                    [tiny] [CPU]│
│ ────────────────────────────────────────── │
│  TRANSCRIPT                                │
│  ┌──────────────────────────────────────┐  │
│  │ 14:32:07  …                          │  │
│  └──────────────────────────────────────┘  │
│  [ Copy last ]              [ Clear ]      │
│                                            │
│  ● Ready                        ~1.4s last │
│ ────────────────────────────────────────── │
│  HOTKEY        [ Alt + Space ]  [ Change ] │
│  OUTPUT        [x] Copy to clipboard       │
│                [ ] Clear after 60 s        │
│  MODEL         tiny-int8  ▾   [ Download ] │
│ ────────────────────────────────────────── │
│  [ Hide to tray ]              [ Quit ]    │
└────────────────────────────────────────────┘
```

Removed: STARTUP section, START/STOP button, language toggle, model
dropdown placeholder, RGB sliders (moved to a header popup).

Accessibility requirements:

- All text ≥ 4.5:1 contrast against its background.
- Body text ≥ 10 pt.
- Font stack: `Inter, Cantarell, DejaVu Sans, sans-serif`.
- Window resizable with a scrollable body; minimum 420×520.
- Full keyboard navigation; visible focus ring.
- Errors displayed in the window, never only in a console.

## 9. Model lifecycle

```
talk model download   → fetch, verify SHA256, write manifest
daemon start          → resolve local path only (local_files_only=True)
load                  → WhisperModel(path, device, compute_type, num_workers=1)
idle > 300 s          → unload, free memory
hotkey press          → reload on demand (first press pays the cost)
```

- No network access after `talk model download`. Enforced by passing a local
  directory and setting offline environment flags before import.
- Model path confined to the application data directory; reject `..`.
- Default model: `tiny` int8. `base` selectable. `large-v3-turbo` remains
  available but is never the default.
- Inference defaults: `beam_size=1`, `best_of=1`, `vad_filter=True`,
  `num_workers=1`, `cpu_threads=2`.
- `language` comes from config. The hardcoded `"en"` at `core/engine.py:106`
  and `core/controller.py:44` is a bug to remove, not behaviour to keep.

## 10. Security requirements

Each maps to an entry in `CURRENT_STATE.md` §4.4.

| ID | Requirement |
|---|---|
| S1 | No startup-registry write at runtime. Autostart only via explicit command. |
| S2 | Audio written to `$XDG_RUNTIME_DIR` (or `%LOCALAPPDATA%\Temp`) with mode `0600`. |
| S3 | WAV deleted in `finally`, including on exception and shutdown. |
| S4 | Own-window / self-target checks fail closed and log. |
| S5 | No bare `except: pass` in hotkey, focus, or audio paths. |
| S6 | Transcript text never logged by default. `--verbose` is opt-in. |
| S7 | Model artifact SHA256-verified before first load. |
| S8 | Exact version pins in `pyproject.toml`; lockfile committed. |
| S9 | Single instance enforced by lock file. |
| S10 | `config.json` written with mode `0600`. |
| S11 | Clipboard auto-clear available; default off, documented. |
| S12 | No synthetic input this milestone, so no focus race exists. |

Additional invariants:

- No `sudo` at runtime. The only privilege ask is `input` group membership,
  granted once by the user.
- No telemetry, no analytics, no outbound connection after model download.

## 11. `talk` CLI contract

```
talk                     start daemon if absent, else print status
talk status              backend, model, hotkey, memory, last error
talk stop                graceful shutdown
talk setup               release Mutter Alt+Space binding, check `input` group
talk setup --undo        restore the binding
talk config              open config file
talk model download ID   fetch + verify
talk logs                tail redacted log
```

Exit codes: `0` success, `1` runtime error, `2` usage error, `3` already running (non-fatal).

Single instance: lock file at `$XDG_RUNTIME_DIR/pisumathu.lock` (Linux) or
`%LOCALAPPDATA%\Pisumathu\pisumathu.lock` (Windows), plus a control socket.

Install:

```bash
uv tool install pisumathu      # preferred
pipx install pisumathu         # fallback
```

## 12. Phase plan

| Phase | Deliverable | Exit test |
|---|---|---|
| 0 | Docs, git hygiene, duplicate deletion, unit tests | `python -m pisumathu` starts |
| 1 | Security S1–S10, config rework, lock file | no WAV residue, no registry write |
| 2 | `pyproject.toml`, `talk` CLI, daemon, IPC | `talk` twice → one process |
| 3 | Hotkey adapters, Alt+Space, `talk setup` | hold/release records on Fedora |
| 4 | Clipboard output, `COPIED` state | text lands in clipboard |
| 5 | UI rework | pill on hotkey, contrast ≥ 4.5:1 |
| 6 | Model download/verify/local-only/idle unload | no sockets while idle |
| 7 | README, dual-platform install | fresh machine → `talk` works |
| 8 | Measurement and tuning | real RSS/CPU numbers recorded |

## 13. Risks

| Risk | Mitigation |
|---|---|
| Alt+Space conflicts on Windows too (system menu) | documented; hotkey configurable |
| `input` group is an unfamiliar privilege ask | `talk setup` explains it, `talk status` diagnoses it |
| evdev hotplug gaps | 2 s device re-scan |
| XWayland pill corners show tint | accepted; GNOME extension is the documented upgrade path |
| Model reload latency on first press after idle | prefetch on hotkey down, before audio starts |
| `<80 MB` unreachable in Python | measured and reported honestly; Rust core is the documented v2 path |
| Wayland clipboard ownership edge cases | Gdk clipboard keeps the daemon as owner |

## 14. Definition of done

1. `talk` launches a detached daemon, no window, tray icon only.
2. Alt+Space held → pill appears → speak → release.
3. Text is in the clipboard within ~2 s.
4. Ctrl+V pastes it into any GNOME Wayland app.
5. `talk stop` exits cleanly with no orphan threads.
6. Nothing starts at OS login.
7. No network traffic after `talk model download`.
8. Identical flow works on Windows 11.
