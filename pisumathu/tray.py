"""Optional system tray icon.

Tray support is best-effort. GNOME needs an AppIndicator extension and the
``libayatana-appindicator`` library; without them pystray cannot attach. A
missing tray is not an error: the daemon is driven by the hotkey and the
``talk`` command.
"""

from __future__ import annotations

import logging

LOG = logging.getLogger("pisumathu.tray")


class Tray:
    def __init__(self, on_show=None, on_quit=None) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None

    def _image(self):
        from PIL import Image, ImageDraw

        size = 64
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((8, 8, size - 8, size - 8), fill=(91, 140, 255, 255))
        draw.rectangle((26, 18, 38, 38), fill=(20, 22, 28, 255))
        return image

    def start(self) -> bool:
        """Attach the tray icon. Returns ``False`` when unsupported."""
        try:
            import pystray
        except ImportError:
            LOG.info("pystray is not installed")
            return False

        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show window", self._show, default=True),
                pystray.MenuItem("Quit", self._quit),
            )
            icon = pystray.Icon("pisumathu", self._image(), "Pisumathu", menu)
        except Exception as exc:  # noqa: BLE001 - tray is optional
            LOG.info("tray icon unavailable: %s", exc)
            return False

        try:
            icon.run_detached()
        except Exception as exc:  # noqa: BLE001 - tray is optional
            LOG.info("tray icon could not start: %s", exc)
            try:
                icon.stop()
            except Exception:  # noqa: BLE001
                pass
            return False

        self._icon = icon
        return True

    def _show(self, *_args) -> None:
        if self._on_show is not None:
            self._on_show()

    def _quit(self, *_args) -> None:
        if self._on_quit is not None:
            self._on_quit()

    def stop(self) -> None:
        icon, self._icon = self._icon, None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:  # noqa: BLE001
            pass
