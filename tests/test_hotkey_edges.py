"""Edge detection for the Linux key reader.

These exercise the exact code path that runs when a key is pressed, without
needing /dev/input access.
"""

import pytest

from pisumathu.hotkey.linux_evdev import EvdevHotkey
from pisumathu.hotkey.parser import parse_hotkey

ALT = 56
LEFT_CTRL = 29
SPACE = 57
KEY_A = 30
PRESS = 1
RELEASE = 0
REPEAT = 2


def build(combo: str = "alt+space"):
    backend = EvdevHotkey(parse_hotkey(combo))
    events: list[str] = []
    backend._on_press_cb = lambda: events.append("press")
    backend._on_release_cb = lambda: events.append("release")
    return backend, events


def test_alt_then_space_fires_once_on_completion():
    backend, events = build()
    backend._handle(ALT, PRESS)
    assert events == []
    backend._handle(SPACE, PRESS)
    assert events == ["press"]


def test_releasing_the_second_key_ends_the_cycle():
    backend, events = build()
    backend._handle(ALT, PRESS)
    backend._handle(SPACE, PRESS)
    backend._handle(SPACE, RELEASE)
    assert events == ["press", "release"]


def test_releasing_the_modifier_first_also_ends_the_cycle():
    backend, events = build()
    backend._handle(ALT, PRESS)
    backend._handle(SPACE, PRESS)
    backend._handle(ALT, RELEASE)
    assert events == ["press", "release"]


def test_auto_repeat_does_not_refire():
    backend, events = build()
    backend._handle(ALT, PRESS)
    backend._handle(SPACE, PRESS)
    for _ in range(5):
        backend._handle(SPACE, REPEAT)
    assert events == ["press"]


def test_unrelated_keys_are_ignored():
    backend, events = build()
    backend._handle(KEY_A, PRESS)
    backend._handle(KEY_A, RELEASE)
    assert events == []


def test_pressing_alt_twice_does_not_refire():
    backend, events = build()
    backend._handle(ALT, PRESS)
    backend._handle(SPACE, PRESS)
    backend._handle(ALT, PRESS)
    assert events == ["press"]


def test_second_cycle_works_after_release():
    backend, events = build()
    for _ in range(2):
        backend._handle(ALT, PRESS)
        backend._handle(SPACE, PRESS)
        backend._handle(SPACE, RELEASE)
        backend._handle(ALT, RELEASE)
    assert events == ["press", "release", "press", "release"]


def test_three_key_combination():
    backend, events = build("ctrl+alt+space")
    backend._handle(LEFT_CTRL, PRESS)
    backend._handle(ALT, PRESS)
    assert events == []
    backend._handle(SPACE, PRESS)
    assert events == ["press"]
    backend._handle(LEFT_CTRL, RELEASE)
    assert events == ["press", "release"]


def test_unknown_keycode_is_ignored():
    backend, events = build()
    backend._handle(9999, PRESS)
    assert events == []


@pytest.mark.parametrize("combo", ["alt+space", "ctrl+space", "super+space"])
def test_each_combo_has_a_distinct_trigger(combo):
    backend, events = build(combo)
    keys = {"alt+space": ALT, "ctrl+space": LEFT_CTRL, "super+space": 125}[combo]
    backend._handle(keys, PRESS)
    backend._handle(SPACE, PRESS)
    assert events == ["press"]
