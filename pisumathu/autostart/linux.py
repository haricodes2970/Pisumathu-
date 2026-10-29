"""XDG autostart for Linux.

Writes ``$XDG_CONFIG_HOME/autostart/pisumathu.desktop``. This is the
standard freedesktop mechanism and is read by GNOME, KDE, and XFCE.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .base import Autostart

DESKTOP_FILE_NAME = "pisumathu.desktop"


def _config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))


def autostart_dir() -> Path:
    return _config_home() / "autostart"


def desktop_path() -> Path:
    return autostart_dir() / DESKTOP_FILE_NAME


def _launch_command() -> str:
    talk = shutil.which("talk")
    if talk:
        return talk
    return f"{sys.executable} -m pisumathu.daemon"


class LinuxAutostart(Autostart):
    name = "linux-xdg"

    def is_enabled(self) -> bool:
        return desktop_path().is_file()

    def enable(self) -> None:
        directory = autostart_dir()
        directory.mkdir(parents=True, exist_ok=True)
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Pisumathu\n"
            "Comment=Offline push-to-talk dictation\n"
            f"Exec={_launch_command()}\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        desktop_path().write_text(content, encoding="utf-8")

    def disable(self) -> None:
        try:
            desktop_path().unlink()
        except FileNotFoundError:
            pass
