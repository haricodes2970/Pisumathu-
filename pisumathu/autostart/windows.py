"""Windows autostart via the per-user ``Run`` key.

Only ever written by an explicit ``talk autostart on``. The daemon never
touches this key, which is what made the old build reappear at login after
being disabled.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .base import Autostart

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Pisumathu"


def _command() -> str:
    talk = Path(sys.executable).parent / "talk.exe"
    if talk.is_file():
        return f'"{talk}"'
    return f'"{sys.executable}" -m pisumathu.daemon'


class WindowsAutostart(Autostart):
    name = "windows-registry"

    def is_enabled(self) -> bool:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, VALUE_NAME)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True

    def enable(self) -> None:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, _command())

    def disable(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        except OSError:
            pass
