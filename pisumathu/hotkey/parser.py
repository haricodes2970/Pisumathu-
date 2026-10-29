"""Hotkey parsing and formatting.

A hotkey is a set of canonical key names. The same spec is consumed by the
evdev backend, the pynput backend, and the settings UI, so the canonical
names are the contract between them.
"""

from __future__ import annotations

from dataclasses import dataclass

MODIFIERS: frozenset[str] = frozenset({"ctrl", "alt", "shift", "super"})

_KEY_ALIASES: dict[str, str] = {
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "super": "super",
    "meta": "super",
    "win": "super",
    "windows": "super",
    "cmd": "super",
    "command": "super",
    "space": "space",
    "spacebar": "space",
    "enter": "enter",
    "return": "enter",
    "tab": "tab",
    "esc": "esc",
    "escape": "esc",
    "backspace": "backspace",
    "delete": "delete",
    "del": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "pageup": "pageup",
    "pagedown": "pagedown",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "capslock": "capslock",
    "pause": "pause",
    "printscreen": "printscreen",
    "menu": "menu",
}

for _letter in "abcdefghijklmnopqrstuvwxyz":
    _KEY_ALIASES[_letter] = _letter
for _digit in "0123456789":
    _KEY_ALIASES[_digit] = _digit
for _number in range(1, 25):
    _KEY_ALIASES[f"f{_number}"] = f"f{_number}"

KEY_ALIASES: dict[str, str] = dict(_KEY_ALIASES)

_DISPLAY: dict[str, str] = {
    "alt": "Alt",
    "ctrl": "Ctrl",
    "shift": "Shift",
    "super": "Super",
    "space": "Space",
    "enter": "Enter",
    "tab": "Tab",
    "esc": "Esc",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "capslock": "CapsLock",
    "pause": "Pause",
    "printscreen": "PrintScreen",
    "menu": "Menu",
}


@dataclass(frozen=True)
class HotkeySpec:
    """A parsed hotkey: canonical key names plus the text the user typed."""

    keys: frozenset[str]
    raw: str

    @property
    def is_modifier_only(self) -> bool:
        return bool(self.keys) and self.keys <= MODIFIERS


def parse_hotkey(text: str) -> HotkeySpec:
    """Parse ``"alt+space"`` into a :class:`HotkeySpec`.

    Raises:
        ValueError: if the text is empty, contains an empty segment, or names
            a key that is not recognised.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("hotkey is empty")

    keys: set[str] = set()
    for part in text.split("+"):
        token = part.strip().lower()
        if not token:
            raise ValueError(f"empty key in hotkey {text!r}")
        canonical = KEY_ALIASES.get(token)
        if canonical is None:
            raise ValueError(f"unknown key {part.strip()!r} in hotkey {text!r}")
        keys.add(canonical)

    if not keys:
        raise ValueError("hotkey is empty")
    return HotkeySpec(keys=frozenset(keys), raw=text.strip())


def _display(key: str) -> str:
    if key in _DISPLAY:
        return _DISPLAY[key]
    if len(key) == 1:
        return key.upper()
    return key.capitalize()


def format_hotkey(spec: HotkeySpec) -> str:
    """Render a spec for display, modifiers first in a stable order."""
    ordered = [m for m in ("ctrl", "alt", "shift", "super") if m in spec.keys]
    rest = sorted(spec.keys - MODIFIERS)
    return "+".join(_display(k) for k in ordered + rest)
