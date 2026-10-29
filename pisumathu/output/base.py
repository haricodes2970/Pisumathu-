"""Output contract: text in, clipboard out."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ClipboardBackend(ABC):
    """A platform mechanism that places text on the clipboard."""

    name: str = "base"

    @abstractmethod
    def copy(self, text: str) -> bool:
        """Place ``text`` on the clipboard. Return ``False`` on failure."""
