"""
ui/tray.py - System tray integration for Pisumathu.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

from PIL import Image, ImageDraw
import pystray


class TrayManager:
    def __init__(
        self,
        app_name: str,
        on_open: Callable[[], None],
        on_quit: Callable[[], None],
    ):
        self._app_name = app_name
        self._on_open = on_open
        self._on_quit = on_quit
        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _create_image(self) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), fill=(13, 15, 20, 255), outline=(0, 229, 255, 255), width=4)
        draw.ellipse((22, 22, 42, 42), fill=(0, 229, 255, 255))
        return image

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem("Open Pisumathu", lambda *_: self._on_open()),
            pystray.MenuItem("Quit", lambda *_: self._on_quit()),
        )

    def start(self) -> None:
        if self._icon is not None:
            return

        self._icon = pystray.Icon(
            name="pisumathu_tray",
            title=self._app_name,
            icon=self._create_image(),
            menu=self._build_menu(),
        )

        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        self._running = True

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            pass
        finally:
            self._icon = None
            self._running = False

    def notify(self, title: str, message: str) -> None:
        if self._icon is None:
            return
        try:
            self._icon.notify(message, title)
        except Exception:
            pass

    @property
    def is_running(self) -> bool:
        return self._running
