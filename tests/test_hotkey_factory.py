import sys

from pisumathu.hotkey.base import FakeHotkey, HotkeyBackend
from pisumathu.hotkey.factory import create_hotkey
from pisumathu.hotkey.parser import parse_hotkey


def test_fake_backend_satisfies_contract():
    backend = FakeHotkey()
    assert isinstance(backend, HotkeyBackend)
    assert backend.name == "fake"

    seen: list[str] = []
    backend.start(lambda: seen.append("press"), lambda: seen.append("release"))
    backend.emit_press()
    backend.emit_release()
    assert seen == ["press", "release"]
    backend.stop()


def test_factory_returns_a_backend():
    backend = create_hotkey(parse_hotkey("alt+space"))
    assert isinstance(backend, HotkeyBackend)
    assert backend.name
    assert hasattr(backend, "selection_note")
    backend.stop()


def test_factory_prefers_evdev_on_linux():
    if sys.platform == "win32":
        return
    backend = create_hotkey(parse_hotkey("alt+space"))
    # Either evdev is selected, or the note explains why it was not.
    assert backend.name == "linux-evdev" or "evdev" in backend.selection_note
    backend.stop()
