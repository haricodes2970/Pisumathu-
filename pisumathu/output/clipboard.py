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

TIMEOUT_SECONDS = 5.0


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


def _linux_backend() -> ClipboardBackend | None:
    if shutil.which("wl-copy") and (
        sys.platform == "linux" and _has_wayland()
    ):
        return CommandClipboard("linux-wl-copy", ["wl-copy"])
    if shutil.which("xsel"):
        return CommandClipboard("linux-xsel", ["xsel", "--clipboard", "--input"])
    if shutil.which("xclip"):
        return CommandClipboard("linux-xclip", ["xclip", "-selection", "clipboard"])
    if shutil.which("wl-copy"):
        return CommandClipboard("linux-wl-copy", ["wl-copy"])
    return None


def _has_wayland() -> bool:
    import os

    return bool(os.environ.get("WAYLAND_DISPLAY"))


class NullClipboard(ClipboardBackend):
    """Used when no clipboard mechanism is available."""

    name = "unavailable"

    def copy(self, text: str) -> bool:
        return False


def default_backend() -> ClipboardBackend:
    if sys.platform == "win32":
        return WindowsClipboard()
    backend = _linux_backend()
    return backend if backend is not None else NullClipboard()


class Clipboard:
    """Facade over the selected backend, with failure containment."""

    def __init__(self, backend: ClipboardBackend | None = None) -> None:
        self._backend = backend if backend is not None else default_backend()

    @property
    def backend(self) -> str:
        return self._backend.name

    @property
    def available(self) -> bool:
        return self._backend.name != "unavailable"

    def copy(self, text: str) -> bool:
        """Copy ``text``. Empty input and backend errors return ``False``."""
        if not text or not text.strip():
            return False
        try:
            return bool(self._backend.copy(text))
        except Exception:  # noqa: BLE001 - output failure must not crash the daemon
            return False

    def clear(self) -> bool:
        """Empty the clipboard. Used by the optional auto-clear timer."""
        try:
            return bool(self._backend.copy(""))
        except Exception:  # noqa: BLE001
            return False
