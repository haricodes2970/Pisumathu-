"""Windows hotkey backend.

pynput reads global key state through a low-level keyboard hook, which is
the only unprivileged option on Windows.
"""

from __future__ import annotations

from .pynput_backend import PynputHotkey


class WindowsHotkey(PynputHotkey):
    name = "windows-pynput"
