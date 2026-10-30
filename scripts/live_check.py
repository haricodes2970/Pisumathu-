#!/usr/bin/env python3
"""Live check: a real keypress, through real audio, to the real clipboard.

This is the strongest check available without a human at the keyboard. It
injects an ``Alt+Space`` press into the kernel through ``/dev/uinput``, so the
daemon's ``/dev/input`` reader sees exactly what it sees on a physical
keypress. While the key is held, the test sentence is played into a temporary
null sink whose monitor is the default recording source, so the recorder
captures real samples through PortAudio. Then the key is released and the
clipboard is read back.

Everything in the path is production code.

Requirements: ``input`` group membership (for /dev/uinput), PipeWire or
PulseAudio, ``espeak-ng``, ``ffmpeg``, ``pactl``, ``paplay`` and a clipboard
backend. It is not run by pytest.

Usage:

    python scripts/live_check.py
"""

from __future__ import annotations

import fcntl
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pisumathu import paths  # noqa: E402
from pisumathu.ipc import DaemonNotRunning, send  # noqa: E402
from pisumathu.output.clipboard import Clipboard  # noqa: E402

SENTENCE = "hello world this is a test of live dictation"
SINK_NAME = "pisumathu-live-check"

# -- uinput ------------------------------------------------------------------

UI_DEV_SETUP = 0x405C5503
UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN = 0x00
EV_KEY = 0x01
KEY_LEFTALT = 56
KEY_SPACE = 57

# struct input_event { timeval; __u16 type; __u16 code; __s32 value; }
INPUT_EVENT = struct.Struct("@llHHi")


class VirtualKeyboard:
    """A throwaway keyboard device created through /dev/uinput."""

    def __init__(self) -> None:
        self._fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self._fd, UI_SET_EVBIT, EV_KEY)
        for code in (KEY_LEFTALT, KEY_SPACE):
            fcntl.ioctl(self._fd, UI_SET_KEYBIT, code)
        # struct uinput_setup { input_id id; char name[80]; __u32 ff_max; }
        setup = struct.pack("HHHH80sI", 0x03, 0x1209, 0x0001, 1, b"pisumathu-live-check", 0)
        fcntl.ioctl(self._fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(self._fd, UI_DEV_CREATE)

    def emit(self, event_type: int, code: int, value: int) -> None:
        os.write(self._fd, INPUT_EVENT.pack(0, 0, event_type, code, value))
        os.write(self._fd, INPUT_EVENT.pack(0, 0, EV_SYN, 0, 0))

    def key(self, code: int, down: bool) -> None:
        self.emit(EV_KEY, code, 1 if down else 0)

    def close(self) -> None:
        try:
            fcntl.ioctl(self._fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self._fd)


# -- audio routing -----------------------------------------------------------


def load_null_sink() -> str:
    """Create a silent sink and return the PulseAudio module id."""
    output = subprocess.run(
        [
            "pactl",
            "load-module",
            "module-null-sink",
            f"sink_name={SINK_NAME}",
            f"sink_properties=device.description={SINK_NAME}",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return output


def default_source() -> str:
    return subprocess.run(
        ["pactl", "get-default-source"], capture_output=True, text=True, check=True
    ).stdout.strip()


def set_default_source(name: str) -> None:
    subprocess.run(["pactl", "set-default-source", name], check=True)


def make_speech(directory: Path) -> Path:
    raw = directory / "raw.wav"
    final = directory / "speech.wav"
    subprocess.run(["espeak-ng", "-w", str(raw), "-s", "150", SENTENCE], check=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-ar",
            "48000",
            "-ac",
            "1",
            str(final),
        ],
        check=True,
    )
    return final


def read_clipboard() -> str:
    """Read the clipboard from whichever display-server path answers.

    ``wl-paste`` blocks until something offers a selection, so an unowned or
    wedged Wayland clipboard hangs rather than returning empty. X11 is tried
    too, because that is the path the app falls back to.
    """
    commands = [
        ["wl-paste", "--no-newline"],
        ["xsel", "--clipboard", "--output"],
    ]
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


# -- daemon ------------------------------------------------------------------


def talk(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pisumathu.cli", *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


def state() -> str:
    try:
        return str(send("status", paths.socket_path(), timeout=2.0).get("state"))
    except (DaemonNotRunning, RuntimeError, OSError):
        return "unreachable"


def wait_for(predicate, timeout: float, label: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    print(f"  [FAIL] timed out waiting for {label}")
    return False


def main() -> int:
    for tool in ("pactl", "paplay", "espeak-ng", "ffmpeg", "wl-paste"):
        if not shutil.which(tool):
            print(f"missing required tool: {tool}")
            return 2

    failures = 0
    module_id = ""
    original_source = default_source()
    keyboard = None
    player = None

    with tempfile.TemporaryDirectory(prefix="pisumathu-live-") as temp:
        try:
            print("1. routing the microphone to a silent test sink")
            module_id = load_null_sink()
            set_default_source(f"{SINK_NAME}.monitor")
            print(f"  source {default_source()}")

            print("2. restarting the daemon on that source")
            talk("stop")
            result = talk()
            if "started" not in result.stdout:
                print(f"  [FAIL] {result.stdout.strip()} {result.stderr.strip()}")
                return 1
            print("  [PASS] daemon started")
            failures += not wait_for(lambda: state() == "idle", 20.0, "daemon idle")

            print("3. creating a virtual keyboard")
            keyboard = VirtualKeyboard()
            print("  [PASS] /dev/uinput device created")

            # Poison the clipboard so a stale value cannot look like success.
            # wl-copy reads the payload on stdin and blocks if it is a terminal,
            # so it goes through the same backend the app uses.
            Clipboard().copy("pisumathu-sentinel")

            print("4. pressing Alt+Space for real")
            speech = make_speech(Path(temp))
            # Let the device scanner notice the new keyboard.
            time.sleep(3.0)
            keyboard.key(KEY_LEFTALT, True)
            keyboard.key(KEY_SPACE, True)
            failures += not wait_for(lambda: state() == "recording", 5.0, "state=recording")
            if state() == "recording":
                print("  [PASS] daemon saw the keypress and started recording")

            print("5. speaking into the sink")
            player = subprocess.Popen(
                ["paplay", f"--device={SINK_NAME}", str(speech)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            player.wait(timeout=30)
            time.sleep(0.4)

            print("6. releasing")
            keyboard.key(KEY_SPACE, False)
            keyboard.key(KEY_LEFTALT, False)
            failures += not wait_for(
                lambda: state() in {"copied", "error"}, 60.0, "a finished state"
            )
            final_state = state()
            print(f"  final state {final_state}")

            status = send("status", paths.socket_path(), timeout=2.0)
            if status.get("last_error"):
                print(f"  last error: {status['last_error']}")
            failures += not (final_state == "copied")

            print("7. clipboard")
            pasted = read_clipboard()
            print(f"  {pasted!r}")
            failures += not bool(pasted.strip())
            failures += "dictation" not in pasted.lower()

        except Exception as exc:  # noqa: BLE001 - report and clean up
            print(f"  [FAIL] {type(exc).__name__}: {exc}")
            failures += 1
        finally:
            print("8. restoring the system")
            if player and player.poll() is None:
                player.kill()
            if keyboard is not None:
                keyboard.close()
            set_default_source(original_source)
            if module_id:
                subprocess.run(
                    ["pactl", "unload-module", module_id],
                    capture_output=True,
                    check=False,
                )
            talk("stop")
            print(f"  source restored to {default_source()}")

    print()
    if failures:
        print(f"RESULT: {failures} check(s) failed")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
