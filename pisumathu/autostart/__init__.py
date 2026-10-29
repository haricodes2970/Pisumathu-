"""Opt-in autostart at OS login."""

from __future__ import annotations

import sys

from .base import Autostart


def get_autostart() -> Autostart:
    if sys.platform == "win32":
        from .windows import WindowsAutostart

        return WindowsAutostart()
    from .linux import LinuxAutostart

    return LinuxAutostart()


__all__ = ["Autostart", "get_autostart"]
