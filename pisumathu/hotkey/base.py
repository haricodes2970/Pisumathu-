"""The hotkey backend contract.

A backend reports two edges: the moment the full key combination is held
down, and the moment any member key is released. Debouncing and state
transitions belong to :mod:`pisumathu.state`, not here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

PressCallback = Callable[[], None]
ReleaseCallback = Callable[[], None]


class HotkeyBackend(ABC):
    """Reads key events and reports combination edges."""

    name: str = "base"
    selection_note: str = ""

    @property
    def error(self) -> str | None:
        """Human-readable reason the backend is not working, if any."""
        return None

    @abstractmethod
    def start(self, on_press: PressCallback, on_release: ReleaseCallback) -> None:
        """Begin listening. Must not block the caller."""

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and release resources. Must be idempotent."""


class FakeHotkey(HotkeyBackend):
    """In-memory backend for tests and headless environments."""

    name = "fake"

    def __init__(self) -> None:
        self.pressed_callback: PressCallback | None = None
        self.released_callback: ReleaseCallback | None = None
        self.started = False

    def start(self, on_press: PressCallback, on_release: ReleaseCallback) -> None:
        self.pressed_callback = on_press
        self.released_callback = on_release
        self.started = True

    def stop(self) -> None:
        self.started = False

    def emit_press(self) -> None:
        if self.pressed_callback:
            self.pressed_callback()

    def emit_release(self) -> None:
        if self.released_callback:
            self.released_callback()
