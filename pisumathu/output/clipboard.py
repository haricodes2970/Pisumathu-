"""Clipboard output.

Wayland clipboard ownership requires a live client, so the Linux path hands
the text to ``wl-copy``, which forks and serves the selection. ``xsel`` is
the fallback for X11-only sessions. Windows uses the Win32 clipboard API
directly.

Synthetic keystroke injection is deliberately absent: it does not work on
GNOME Wayland and is out of scope for this milestone.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

from .base import ClipboardBackend

# A healthy wl-copy returns in milliseconds; a wedged Wayland clipboard blocks
# until the timeout. Keeping this short bounds the cost of falling back to the
# next backend instead of stalling dictation for five seconds.
TIMEOUT_SECONDS = 2.0


class CommandClipboard(ClipboardBackend):
    """Clipboard backend driven by an external command reading stdin."""

    def __init__(self, name: str, argv: list[str]) -> None:
        self.name = name
        self._argv = argv

    def copy(self, text: str) -> bool:
        try:
            result = subprocess.run(
                self._argv,
                input=text.encode("utf-8"),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return result.returncode == 0


class WindowsClipboard(ClipboardBackend):
    """Win32 clipboard via ctypes."""

    name = "windows-win32"
    _CF_UNICODETEXT = 13
    _GMEM_MOVEABLE = 0x0002

    def copy(self, text: str) -> bool:
        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

        payload = text.encode("utf-16-le") + b"\x00\x00"
        if not user32.OpenClipboard(None):
            return False
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(self._GMEM_MOVEABLE, len(payload))
            if not handle:
                return False
            pointer = kernel32.GlobalLock(handle)
            if not pointer:
                return False
            try:
                ctypes.memmove(pointer, payload, len(payload))
            finally:
                kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(self._CF_UNICODETEXT, handle):
                return False
        finally:
            user32.CloseClipboard()
        return True


class NullClipboard(ClipboardBackend):
    """Used when no clipboard mechanism is available."""

    name = "unavailable"

    def copy(self, text: str) -> bool:
        return False


def _linux_backends() -> list[ClipboardBackend]:
    """Every usable Linux clipboard, in preference order.

    A wedged Wayland clipboard happens: killing a ``wl-copy`` that still owns
    the selection can leave the compositor unresponsive, and ``wl-copy`` then
    blocks until it times out. X11 clients still work through XWayland, and
    the compositor syncs the selection back, so keeping a fallback means a
    transcript is never lost to a stuck clipboard.
    """
    backends: list[ClipboardBackend] = []
    if shutil.which("wl-copy"):
        backends.append(CommandClipboard("linux-wl-copy", ["wl-copy"]))
    if shutil.which("xsel"):
        backends.append(CommandClipboard("linux-xsel", ["xsel", "--clipboard", "--input"]))
    if shutil.which("xclip"):
        backends.append(CommandClipboard("linux-xclip", ["xclip", "-selection", "clipboard"]))
    return backends


def default_backends() -> list[ClipboardBackend]:
    if sys.platform == "win32":
        return [WindowsClipboard()]
    backends = _linux_backends()
    return backends if backends else [NullClipboard()]


def default_backend() -> ClipboardBackend:
    return default_backends()[0]


class Clipboard:
    """Facade over the clipboard backends, with failure containment.

    Backends are tried in order until one succeeds, so a stuck display-server
    clipboard degrades to the next mechanism instead of losing the text.
    """

    def __init__(self, backend: ClipboardBackend | None = None) -> None:
        self._backends = [backend] if backend is not None else default_backends()
        self._used: str | None = None

    @property
    def backend(self) -> str:
        return self._used or self._backends[0].name

    @property
    def available(self) -> bool:
        return any(b.name != "unavailable" for b in self._backends)

    def copy(self, text: str) -> bool:
        """Copy ``text``. Empty input and backend errors return ``False``."""
        if not text or not text.strip():
            return False
        for candidate in self._backends:
            if candidate.name == "unavailable":
                continue
            try:
                if candidate.copy(text):
                    self._used = candidate.name
                    return True
            except Exception:  # noqa: BLE001 - output failure must not crash
                continue
        return False

    def clear(self) -> bool:
        """Empty the clipboard. Used by the optional auto-clear timer."""
        for candidate in self._backends:
            if candidate.name == "unavailable":
                continue
            try:
                if candidate.copy(""):
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False
