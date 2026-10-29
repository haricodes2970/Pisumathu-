"""Hotkey adapters: one interface, one implementation per platform."""

from .parser import HotkeySpec, format_hotkey, parse_hotkey

__all__ = ["HotkeySpec", "format_hotkey", "parse_hotkey"]
