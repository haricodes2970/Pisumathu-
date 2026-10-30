import pytest

from pisumathu.hotkey.parser import (
    MODIFIERS,
    HotkeySpec,
    format_hotkey,
    parse_hotkey,
)


def test_parses_alt_space():
    spec = parse_hotkey("alt+space")
    assert spec.keys == frozenset({"alt", "space"})


def test_tolerates_whitespace_and_case():
    spec = parse_hotkey("  ALT +  Space  ")
    assert spec.keys == frozenset({"alt", "space"})


def test_aliases_resolve():
    assert parse_hotkey("control+option").keys == frozenset({"ctrl", "alt"})
    assert parse_hotkey("win+space").keys == frozenset({"super", "space"})
    assert parse_hotkey("cmd+space").keys == frozenset({"super", "space"})
    assert parse_hotkey("return").keys == frozenset({"enter"})
    assert parse_hotkey("escape").keys == frozenset({"esc"})


@pytest.mark.parametrize("text", ["", "   ", "alt+", "+space", "ctrl++space"])
def test_empty_segments_rejected(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


@pytest.mark.parametrize("text", ["ctrl+banana", "alt+hyper", "f99"])
def test_unknown_keys_rejected(text):
    with pytest.raises(ValueError):
        parse_hotkey(text)


def test_duplicate_keys_collapse():
    spec = parse_hotkey("alt+alt+space")
    assert spec.keys == frozenset({"alt", "space"})


def test_letters_and_digits():
    assert parse_hotkey("ctrl+a").keys == frozenset({"ctrl", "a"})
    assert parse_hotkey("ctrl+7").keys == frozenset({"ctrl", "7"})


def test_function_keys():
    assert parse_hotkey("f12").keys == frozenset({"f12"})


def test_modifier_only_detection():
    assert parse_hotkey("ctrl+alt").is_modifier_only
    assert not parse_hotkey("ctrl+space").is_modifier_only
    assert MODIFIERS == frozenset({"ctrl", "alt", "shift", "super"})


def test_format_orders_modifiers_first():
    assert format_hotkey(parse_hotkey("ALT + Space")) == "Alt+Space"
    assert format_hotkey(parse_hotkey("space+shift+ctrl")) == "Ctrl+Shift+Space"
    assert format_hotkey(parse_hotkey("f5")) == "F5"
    assert format_hotkey(parse_hotkey("ctrl+a")) == "Ctrl+A"


def test_format_round_trips_through_parse():
    for text in ["alt+space", "ctrl+shift+space", "super+d", "f11"]:
        assert parse_hotkey(format_hotkey(parse_hotkey(text))).keys == parse_hotkey(text).keys


def test_spec_is_hashable_and_frozen():
    spec = parse_hotkey("alt+space")
    assert isinstance(spec, HotkeySpec)
    assert hash(spec) == hash(parse_hotkey("alt+space"))
    with pytest.raises(AttributeError):
        spec.keys = frozenset()  # type: ignore[misc]
