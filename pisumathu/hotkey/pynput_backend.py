"""Key event handling shared by the pynput-based backends.

pynput is the only option on Windows. On Linux it is the X11 fallback used
when evdev is unavailable; it does not see keys under a native Wayland
session.
"""

from __future__ import annotations

import threading

from .base import HotkeyBackend, PressCallback, ReleaseCallback
from .parser import HotkeySpec


def _build_key_map() -> dict[object, str]:
    from pynput import keyboard

    key = keyboard.Key
    mapping: dict[object, str] = {
        key.alt: "alt",
        key.alt_l: "alt",
        key.alt_r: "alt",
        key.alt_gr: "alt",
        key.ctrl: "ctrl",
        key.ctrl_l: "ctrl",
        key.ctrl_r: "ctrl",
        key.shift: "shift",
        key.shift_l: "shift",
        key.shift_r: "shift",
        key.cmd: "super",
        key.cmd_l: "super",
        key.cmd_r: "super",
        key.space: "space",
        key.enter: "enter",
        key.tab: "tab",
        key.esc: "esc",
        key.backspace: "backspace",
        key.delete: "delete",
        key.insert: "insert",
        key.home: "home",
        key.end: "end",
        key.page_up: "pageup",
        key.page_down: "pagedown",
        key.up: "up",
        key.down: "down",
        key.left: "left",
        key.right: "right",
        key.caps_lock: "capslock",
        key.pause: "pause",
        key.print_screen: "printscreen",
        key.menu: "menu",
    }
    for number in range(1, 21):
        attribute = getattr(key, f"f{number}", None)
        if attribute is not None:
            mapping[attribute] = f"f{number}"
    return mapping


class PynputHotkey(HotkeyBackend):
    """Hold-to-talk detection built on ``pynput.keyboard.Listener``."""

    name = "pynput"

    def __init__(self, spec: HotkeySpec) -> None:
        self.spec = spec
        self._pressed: set[str] = set()
        self._active = False
        self._listener = None
        self._lock = threading.Lock()
        self._key_map: dict[object, str] | None = None

    def _canonical(self, key: object) -> str | None:
        if self._key_map is None:
            self._key_map = _build_key_map()
        mapped = self._key_map.get(key)
        if mapped is not None:
            return mapped
        char = getattr(key, "char", None)
        if isinstance(char, str) and char:
            return char.lower()
        return None

    def _on_press(self, key: object) -> None:
        name = self._canonical(key)
        if name is None:
            return
        fire = False
        with self._lock:
            self._pressed.add(name)
            if not self._active and self.spec.keys <= self._pressed:
                self._active = True
                fire = True
        if fire and self._on_press_cb:
            self._on_press_cb()

    def _on_release(self, key: object) -> None:
        name = self._canonical(key)
        if name is None:
            return
        fire = False
        with self._lock:
            self._pressed.discard(name)
            if self._active and not self.spec.keys <= self._pressed:
                self._active = False
                fire = True
        if fire and self._on_release_cb:
            self._on_release_cb()

    def start(self, on_press: PressCallback, on_release: ReleaseCallback) -> None:
        if self._listener is not None:
            return
        from pynput import keyboard

        self._on_press_cb = on_press
        self._on_release_cb = on_release
        listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        listener.daemon = True
        listener.start()
        self._listener = listener

    def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is None:
            return
        try:
            listener.stop()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass
        self._pressed.clear()
        self._active = False
