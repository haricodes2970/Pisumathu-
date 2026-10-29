"""Autostart contract.

Autostart is opt-in. Nothing in the daemon calls :meth:`Autostart.enable`;
only the explicit ``talk autostart on`` command does.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Autostart(ABC):
    name: str = "base"

    @abstractmethod
    def is_enabled(self) -> bool: ...

    @abstractmethod
    def enable(self) -> None: ...

    @abstractmethod
    def disable(self) -> None: ...
