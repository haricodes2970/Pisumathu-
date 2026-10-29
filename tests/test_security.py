import os
import stat

from pisumathu import security


def test_secure_audio_path_is_owner_only(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    path = security.secure_audio_path()
    assert path.exists()
    assert path.suffix == ".wav"
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_secure_audio_path_is_unique(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    assert security.secure_audio_path() != security.secure_audio_path()


def test_redact_hides_content():
    assert "secret" not in security.redact("secret words")

    assert security.redact(None) == ""


def test_remove_quietly_tolerates_missing(tmp_path):
    security.remove_quietly(tmp_path / "nope.wav")
    target = tmp_path / "a.wav"
    target.write_bytes(b"x")
    security.remove_quietly(target)
    assert not target.exists()
