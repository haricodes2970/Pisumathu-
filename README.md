# Pisumathu

Offline push-to-talk dictation for Linux and Windows.

Hold a hotkey, speak, release. The text is in your clipboard. Press `Ctrl+V`
wherever you want it.

No account, no cloud, no telemetry. After the model download it makes no
network connections at all.

```
$ talk
pisumathu started in the background.
state          idle
model          tiny (not loaded)
hotkey         Alt+Space  [linux-evdev]
clipboard      linux-wl-copy
```

---

## Why clipboard instead of auto-paste

Wayland gives no way for an ordinary application to type into another one.
`xdotool` and `pynput` are X11-only, `wtype` needs wlroots (not GNOME), and
`ydotool` needs a privileged daemon. Rather than ship something that works on
one desktop and silently fails on another, Pisumathu puts the text on the
clipboard, which works everywhere.

## Requirements

| | |
|---|---|
| Python | 3.11 or newer |
| Linux | Fedora/GNOME on Wayland or X11, PipeWire or PulseAudio |
| Windows | 10 or 11 |
| Disk | ~75 MB for the `tiny` model, ~1.5 GB for `large-v3-turbo` |
| Memory | ~120 MB while a model is loaded, ~40 MB idle |

## Install

```bash
git clone https://github.com/haricodes2970/Pisumathu-.git
cd Pisumathu-

uv venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
uv pip install -e .
```

To get a global `talk` command:

```bash
uv tool install .                  # preferred
pipx install .                     # alternative
```

## First run on Linux

Two one-time steps, both explicit:

```bash
talk setup
```

This does two things and tells you the result:

1. **Frees `Alt+Space`.** GNOME binds it to the window menu
   (`org.gnome.desktop.wm.keybindings activate-window-menu`). Pisumathu clears
   that binding so the key reaches the app. Undo any time with
   `talk setup --undo`.
2. **Checks keyboard access.** Reading keys under Wayland requires membership
   of the `input` group:

   ```bash
   sudo usermod -aG input $USER
   ```

   Log out and back in afterwards.

If you would rather keep `Alt+Space`, change the hotkey instead:

```bash
talk config          # opens config.json
```

```json
{ "hotkey": "ctrl+alt+space" }
```

## Download a model

```bash
talk model download tiny
```

Every file is verified against the SHA256 the Hugging Face API reports. A
corrupt or tampered download is rejected rather than loaded.

| Model | Size | Notes |
|---|---|---|
| `tiny` | 75 MB | default, fastest, good for short commands |
| `base` | 145 MB | better accuracy, still quick |
| `small` | 480 MB | good balance |
| `medium` | 1.5 GB | slower on CPU |
| `large-v3-turbo` | 1.6 GB | best accuracy, needs a GPU to feel fast |

## Use it

```bash
talk
```

Then hold your hotkey, speak, release. The pill shows recording, then
transcribing, then a green check. The text is on your clipboard.

| Command | What it does |
|---|---|
| `talk` | start the daemon, or show status if it is already running |
| `talk status` | state, model, hotkey backend, clipboard backend, last error |
| `talk stop` | shut the daemon down |
| `talk setup` | free `Alt+Space`, check keyboard access |
| `talk setup --undo` | restore the GNOME shortcut |
| `talk config` | open `config.json` |
| `talk model download <name>` | fetch and verify a model |
| `talk autostart on\|off` | opt in or out of starting at login |
| `talk logs` | last 50 log lines |

Nothing starts at login unless you run `talk autostart on`.

## How it works

```
talk ──► control socket ──► daemon
                              │
        ┌──────────┬──────────┼──────────┬───────────┐
        │          │          │          │           │
    hotkey      audio       asr       clipboard     ui
   /dev/input  16 kHz    faster-     wl-copy /    pill +
   or pynput    mono      whisper     Win32      window
```

- **Hotkey.** On Linux, keys are read straight from `/dev/input/event*`, which
  is the only method that works under Wayland. On Windows, a low-level
  keyboard hook is used. The combination is parsed from your config.
- **Audio.** A stream stays open for the life of the daemon and keeps a 200 ms
  pre-roll, so the first syllable is not clipped.
- **Transcription.** faster-whisper with a local model directory and
  `local_files_only=True`. No network access.
- **Clipboard.** `wl-copy` on Wayland, `xsel`/`xclip` on X11, the Win32
  clipboard API on Windows.
- **Memory.** The model is unloaded after five idle minutes and reloaded on
  the next press.

## Configuration

`~/.local/share/pisumathu/config.json` (Linux) or
`%LOCALAPPDATA%\pisumathu\config.json` (Windows). The file is created with
mode `0600`.

| Key | Default | Meaning |
|---|---|---|
| `hotkey` | `"alt+space"` | hold-to-talk combination |
| `model` | `"tiny"` | model directory name |
| `device` | `"auto"` | `auto`, `cpu` or `cuda` |
| `compute_type` | `"int8"` | ctranslate2 compute type |
| `language` | `null` | `null` detects automatically, or `"en"`, `"de"`, … |
| `beam_size` | `1` | higher is slower and slightly more accurate |
| `vad_filter` | `true` | skip silence |
| `clipboard_auto_clear_seconds` | `0` | `0` keeps the text until you copy again |
| `idle_unload_seconds` | `300` | unload the model after this long idle |
| `show_pill` | `true` | show the floating indicator |
| `show_window_on_start` | `false` | open the control panel at launch |
| `autostart` | `false` | informational; use `talk autostart` |
| `verbose` | `false` | also log to the terminal |

## Privacy

- Recorded audio is written to `$XDG_RUNTIME_DIR/pisumathu` with mode `0600`
  and deleted immediately after transcription, including on failure.
- Transcript text is never written to a log. `talk logs` shows events only.
- No outbound connection after `talk model download`.
- No `sudo` at runtime. `input` group membership is the only elevated grant,
  and it is yours to give.

## Troubleshooting

**`hotkey: unavailable` in `talk status`**

```bash
id -nG | grep input        # is the group there?
ls -l /dev/input/event*    # readable?
```

If the group was just added, log out and back in.

**Nothing happens when I hold the hotkey**

Another app may own the combination. `talk setup` frees `Alt+Space` on GNOME;
for anything else, change `hotkey` in the config.

**`no speech detected`**

The model ran but heard nothing. Check the microphone is not muted, and that
`pw-record`/`parecord` captures audio.

**The pill does not appear**

On GNOME the pill is an XWayland window. It needs `DISPLAY` to be set, which
it is in a normal session. Check `talk logs`.

**Clipboard stays empty**

`talk status` reports the clipboard backend. If it says `unavailable`, install
`wl-clipboard` (`sudo dnf install wl-clipboard`).

## Development

```bash
uv pip install -e ".[dev]"
pytest -q
ruff check .
```

See `AGENTS.md` for the architecture rules and `CURRENT_STATE.md` for the
history of the rewrite.

## License

MIT. See `LICENSE`.
