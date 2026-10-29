import os
import stat

from pisumathu import paths


def test_runtime_dir_is_private(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    directory = paths.runtime_dir()
    assert directory.is_dir()
    assert directory.name == "pisumathu"
    if os.name != "nt":
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_config_path_under_app_data(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert paths.config_path() == tmp_path / "pisumathu" / "config.json"


def test_models_dir_is_created(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    directory = paths.models_dir()
    assert directory.is_dir()
    assert directory == tmp_path / "pisumathu" / "models"


def test_socket_and_lock_live_in_runtime_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert paths.socket_path().parent == paths.runtime_dir()
    assert paths.lock_path().parent == paths.runtime_dir()
