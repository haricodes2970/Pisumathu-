import wave

import pytest

from pisumathu.audio.buffer import PreRollBuffer
from pisumathu.audio.capture import Recorder


def test_buffer_is_bounded_and_evicts_oldest():
    buffer = PreRollBuffer(3)
    for chunk in [b"a", b"b", b"c", b"d", b"e"]:
        buffer.push(chunk)
    assert len(buffer) == 3
    assert buffer.drain() == [b"c", b"d", b"e"]


def test_drain_empties_the_buffer():
    buffer = PreRollBuffer(4)
    buffer.push(b"x")
    assert buffer.drain() == [b"x"]
    assert len(buffer) == 0
    assert buffer.drain() == []


def test_zero_capacity_keeps_nothing():
    buffer = PreRollBuffer(0)
    buffer.push(b"x")
    assert len(buffer) == 0


def test_negative_capacity_rejected():
    with pytest.raises(ValueError):
        PreRollBuffer(-1)


def test_stop_without_start_raises():
    recorder = Recorder()
    with pytest.raises(RuntimeError):
        recorder.stop()


def test_start_is_idempotent():
    recorder = Recorder()
    assert recorder.is_recording is False
    assert recorder.start() is True
    assert recorder.is_recording is True
    assert recorder.start() is False


def test_cancel_drops_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    recorder = Recorder()
    recorder.start()
    recorder.cancel()
    assert recorder.is_recording is False
    with pytest.raises(RuntimeError):
        recorder.stop()


def test_stop_writes_readable_wav(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    recorder = Recorder(samplerate=16_000, channels=1)
    recorder._preroll.push(b"\x00\x00" * 512)
    recorder.start()
    recorder._frames.append(b"\x01\x00" * 512)  # type: ignore[union-attr]
    path = recorder.stop()

    assert path.exists()
    assert path.parent == tmp_path / "pisumathu"
    with wave.open(str(path), "rb") as handle:
        assert handle.getframerate() == 16_000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == 1024


def test_preroll_is_included_in_recording(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    recorder = Recorder(samplerate=16_000, blocksize=1024)
    recorder._preroll.push(b"\x00\x00" * 1024)
    recorder.start()
    assert len(recorder._frames) == 1  # type: ignore[arg-type]
    recorder.cancel()
