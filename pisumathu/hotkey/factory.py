"""Select the best available hotkey backend for this machine."""

from __future__ import annotations

import sys

from .base import HotkeyBackend
from .parser import HotkeySpec


def create_hotkey(spec: HotkeySpec) -> HotkeyBackend:
    """Return the best backend for the current platform.

    Windows always uses pynput. Linux prefers evdev and falls back to the
    X11 listener, recording why it fell back.
    """
    if sys.platform == "win32":
        from .windows import WindowsHotkey

        return WindowsHotkey(spec)

    evdev_reason = "not attempted"
    try:
        from .linux_evdev import EvdevHotkey

        available, evdev_reason = EvdevHotkey.probe()
        if available:
            backend = EvdevHotkey(spec)
            backend.selection_note = f"evdev: {evdev_reason}"
            return backend
    except Exception as exc:  # noqa: BLE001 - fall through to X11
        evdev_reason = str(exc)

    from .linux_x11 import X11Hotkey

    backend = X11Hotkey(spec)
    backend.selection_note = f"evdev unavailable ({evdev_reason}); using X11 listener"
    return backend
