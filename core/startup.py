"""
core/startup.py - Windows autostart helper.

Manages HKCU Run key so Pisumathu can launch on user logon without admin rights.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


APP_NAME = "Pisumathu"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        return f'"{exe}" --tray'

    python_exe = Path(sys.executable)
    script_path = Path(__file__).resolve().parent.parent / "pisumathu.py"
    return f'"{python_exe}" "{script_path}" --tray'


def _open_run_key(write: bool = False):
    if winreg is None:
        raise RuntimeError("Windows registry is unavailable on this platform.")
    access = winreg.KEY_READ
    if write:
        access = winreg.KEY_SET_VALUE | winreg.KEY_READ
    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, access)


def is_startup_enabled() -> bool:
    if winreg is None:
        return False

    try:
        with _open_run_key(write=False) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return str(value).strip() != ""
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> bool:
    if winreg is None:
        return False

    command = _startup_command()
    try:
        with _open_run_key(write=True) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
