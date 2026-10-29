"""X11 fallback backend.

Only used when evdev is unavailable. Under a native Wayland session pynput
sees nothing, which is why evdev is the preferred Linux path.
"""

from __future__ import annotations

from .pynput_backend import PynputHotkey


class X11Hotkey(PynputHotkey):
    name = "linux-x11-pynput"
