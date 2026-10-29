"""Linux hotkey backend reading ``/dev/input/event*`` directly.

Pure Python: no C extension, so installing the app never needs a compiler
or Python development headers. Events are parsed from the kernel's
``input_event`` struct.

This is the only approach that works under a native Wayland session,
because it bypasses the display server. It requires the user to be in the
``input`` group.

Devices are never grabbed. Events still reach the focused application, so
the conflicting desktop shortcut is released by ``talk setup`` instead.
"""

from __future__ import annotations

import fcntl
import os
import select
import struct
import threading
from pathlib import Path

from .base import HotkeyBackend, PressCallback, ReleaseCallback
from .parser import HotkeySpec

RESCAN_INTERVAL_SECONDS = 2.0
EV_SYN = 0x00
EV_KEY = 0x01
KEY_RELEASE = 0
KEY_PRESS = 1
KEY_REPEAT = 2

# struct input_event is { struct timeval time; __u16 type; __u16 code; __s32 value; }
# timeval is two longs, which is 8 bytes each on 64-bit and 4 bytes each on 32-bit.
_LONG_SIZE = struct.calcsize("@l")
_TIMEVAL_FORMAT = "@ll" if _LONG_SIZE == 8 else "@ii"
INPUT_EVENT = struct.Struct(_TIMEVAL_FORMAT + "HHi")
READ_BATCH = 64

# linux/input-event-codes.h values. Only the keys a hotkey can reasonably use.
KEY_CODES: dict[int, str] = {
    1: "esc",
    2: "1",
    3: "2",
    4: "3",
    5: "4",
    6: "5",
    7: "6",
    8: "7",
    9: "8",
    10: "9",
    11: "0",
    14: "backspace",
    15: "tab",
    16: "q",
    17: "w",
    18: "e",
    19: "r",
    20: "t",
    21: "y",
    22: "u",
    23: "i",
    24: "o",
    25: "p",
    28: "enter",
    29: "ctrl",
    30: "a",
    31: "s",
    32: "d",
    33: "f",
    34: "g",
    35: "h",
    36: "j",
    37: "k",
    38: "l",
    42: "shift",
    44: "z",
    45: "x",
    46: "c",
    47: "v",
    48: "b",
    49: "n",
    50: "m",
    54: "shift",
    56: "alt",
    57: "space",
    58: "capslock",
    59: "f1",
    60: "f2",
    61: "f3",
    62: "f4",
    63: "f5",
    64: "f6",
    65: "f7",
    66: "f8",
    67: "f9",
    68: "f10",
    87: "f11",
    88: "f12",
    96: "enter",
    97: "ctrl",
    99: "printscreen",
    100: "alt",
    102: "home",
    103: "up",
    104: "pageup",
    105: "left",
    106: "right",
    107: "end",
    108: "down",
    109: "pagedown",
    110: "insert",
    111: "delete",
    119: "pause",
    125: "super",
    126: "super",
    139: "menu",
}
for _index, _code in enumerate(range(183, 195), start=13):
    KEY_CODES[_code] = f"f{_index}"


def list_event_devices() -> list[str]:
    """Return every readable ``/dev/input/event*`` path."""
    directory = Path("/dev/input")
    if not directory.is_dir():
        return []
    return sorted(str(path) for path in directory.glob("event*"))


def _device_name(fd: int) -> str:
    """Best-effort device name via EVIOCGNAME."""
    length = 256
    request = (2 << 30) | (length << 16) | (ord("E") << 8) | 0x06
    buffer = bytearray(length)
    try:
        fcntl.ioctl(fd, request, buffer)
    except OSError:
        return "unknown"
    return buffer.split(b"\x00", 1)[0].decode("utf-8", "replace") or "unknown"


class EvdevHotkey(HotkeyBackend):
    """Hold-to-talk detection across every readable input device."""

    name = "linux-evdev"

    def __init__(self, spec: HotkeySpec) -> None:
        self.spec = spec
        self._fds: dict[str, int] = {}
        self._buffers: dict[str, bytes] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pressed: set[str] = set()
        self._active = False
        self._error: str | None = None
        self._scanner: threading.Thread | None = None
        self._on_press_cb: PressCallback | None = None
        self._on_release_cb: ReleaseCallback | None = None

    # -- capability probe ---------------------------------------------

    @staticmethod
    def probe() -> tuple[bool, str]:
        """Report whether at least one input device can be opened."""
        devices = list_event_devices()
        if not devices:
            return False, "no /dev/input/event* devices found"

        opened = 0
        last_error = ""
        for path in devices:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except PermissionError as exc:
                last_error = str(exc)
                continue
            except OSError as exc:
                last_error = str(exc)
                continue
            os.close(fd)
            opened += 1

        if opened:
            return True, f"{opened} readable input device(s)"
        return (
            False,
            "cannot read /dev/input (add this user to the 'input' group)"
            + (f": {last_error}" if last_error else ""),
        )

    @property
    def error(self) -> str | None:
        return self._error

    # -- lifecycle ----------------------------------------------------

    def start(self, on_press: PressCallback, on_release: ReleaseCallback) -> None:
        if self._scanner is not None:
            return
        self._on_press_cb = on_press
        self._on_release_cb = on_release
        self._stop.clear()
        scanner = threading.Thread(target=self._scan_loop, name="hotkey-scan", daemon=True)
        self._scanner = scanner
        scanner.start()

    def stop(self) -> None:
        self._stop.set()
        scanner, self._scanner = self._scanner, None
        if scanner is not None:
            scanner.join(timeout=3.0)
        for thread in list(self._threads.values()):
            thread.join(timeout=2.0)
        self._threads.clear()
        for path in list(self._fds):
            self._close(path)
        with self._lock:
            self._pressed.clear()
            self._active = False

    # -- device management --------------------------------------------

    def _scan_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._scan_once()
            except Exception as exc:  # noqa: BLE001 - keep scanning
                self._error = f"device scan failed: {exc}"
            self._stop.wait(RESCAN_INTERVAL_SECONDS)

    def _scan_once(self) -> None:
        paths = set(list_event_devices())
        for path in paths - set(self._fds):
            if self._stop.is_set():
                return
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            self._fds[path] = fd
            self._buffers[path] = b""
            thread = threading.Thread(
                target=self._read_loop,
                args=(path, fd),
                name=f"hotkey-{Path(path).name}",
                daemon=True,
            )
            self._threads[path] = thread
            thread.start()

        for path in set(self._fds) - paths:
            self._close(path)

    def _close(self, path: str) -> None:
        fd = self._fds.pop(path, None)
        self._buffers.pop(path, None)
        self._threads.pop(path, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    # -- event reading ------------------------------------------------

    def _read_loop(self, path: str, fd: int) -> None:
        size = INPUT_EVENT.size
        while not self._stop.is_set():
            try:
                ready, _, _ = select.select([fd], [], [], 0.5)
            except (OSError, ValueError):
                return
            if not ready:
                continue
            try:
                chunk = os.read(fd, size * READ_BATCH)
            except BlockingIOError:
                continue
            except OSError:
                return
            if not chunk:
                return

            buffer = self._buffers.get(path, b"") + chunk
            offset = 0
            while len(buffer) - offset >= size:
                _, _, event_type, code, value = INPUT_EVENT.unpack_from(buffer, offset)
                offset += size
                if event_type == EV_KEY and value in (KEY_PRESS, KEY_RELEASE):
                    self._handle(code, value)
            self._buffers[path] = buffer[offset:]

    def _handle(self, code: int, value: int) -> None:
        name = KEY_CODES.get(code)
        if name is None:
            return

        fire_press = False
        fire_release = False
        with self._lock:
            if value == KEY_PRESS:
                self._pressed.add(name)
                if not self._active and self.spec.keys <= self._pressed:
                    self._active = True
                    fire_press = True
            elif value == KEY_RELEASE:
                self._pressed.discard(name)
                if self._active and not self.spec.keys <= self._pressed:
                    self._active = False
                    fire_release = True

        if fire_press and self._on_press_cb:
            self._on_press_cb()
        if fire_release and self._on_release_cb:
            self._on_release_cb()
