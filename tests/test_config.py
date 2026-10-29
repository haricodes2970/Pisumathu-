import json
import os
import stat

from pisumathu.config import Config, load_config, save_config


def test_missing_file_returns_defaults(tmp_path):
    config = load_config(tmp_path / "absent.json")
    assert config.hotkey == "alt+space"
    assert config.model == "tiny"
    assert config.beam_size == 1
    assert config.vad_filter is True
    assert config.autostart is False


def test_corrupt_json_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    assert load_config(path) == Config()


def test_non_object_json_returns_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert load_config(path) == Config()


def test_unknown_keys_are_ignored(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkey": "ctrl+space", "nonsense": 1}), encoding="utf-8")
    config = load_config(path)
    assert config.hotkey == "ctrl+space"
    assert not hasattr(config, "nonsense")


def test_partial_file_merges_with_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"model": "base"}), encoding="utf-8")
    config = load_config(path)
    assert config.model == "base"
    assert config.idle_unload_seconds == 300


def test_wrong_types_fall_back_to_defaults(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps({"beam_size": "five", "vad_filter": "yes", "hotkey": 42}),
        encoding="utf-8",
    )
    config = load_config(path)
    assert config.beam_size == 1
    assert config.vad_filter is True
    assert config.hotkey == "alt+space"


def test_language_accepts_null(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"language": None}), encoding="utf-8")
    assert load_config(path).language is None


def test_round_trip(tmp_path):
    path = tmp_path / "config.json"
    original = Config(hotkey="ctrl+shift+space", model="base", language="de", beam_size=5)
    save_config(original, path)
    assert load_config(path) == original


def test_saved_file_is_owner_only(tmp_path):
    path = tmp_path / "config.json"
    save_config(Config(), path)
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_save_creates_parent_dirs(tmp_path):
    path = tmp_path / "deep" / "nested" / "config.json"
    save_config(Config(), path)
    assert path.is_file()


def test_save_leaves_no_temp_files(tmp_path):
    save_config(Config(), tmp_path / "config.json")
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".config-")]
    assert leftovers == []
