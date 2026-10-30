import wave

import numpy as np
import pytest

from pisumathu.asr.engine import _load_audio


def write_wav(path, rate=16_000, channels=1, frames=b"\x00\x00" * 100):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return path


def test_loads_16k_mono_as_float32(tmp_path):
    samples = np.array([0, 16384, -16384], dtype=np.int16)
    path = write_wav(tmp_path / "a.wav", frames=samples.tobytes())

    audio = _load_audio(path)

    assert audio is not None
    assert audio.dtype == np.float32
    assert len(audio) == 3
    assert audio[0] == pytest.approx(0.0)
    assert audio[1] == pytest.approx(0.5, abs=1e-3)
    assert audio[2] == pytest.approx(-0.5, abs=1e-3)


def test_empty_wav_returns_none(tmp_path):
    path = write_wav(tmp_path / "empty.wav", frames=b"")
    assert _load_audio(path) is None


def test_missing_file_returns_none(tmp_path):
    assert _load_audio(tmp_path / "absent.wav") is None


def test_non_wav_returns_none(tmp_path):
    path = tmp_path / "junk.wav"
    path.write_bytes(b"not a wav file at all")
    assert _load_audio(path) is None


def test_wrong_sample_rate_raises(tmp_path):
    path = write_wav(tmp_path / "low.wav", rate=8000)
    with pytest.raises(ValueError, match="16000"):
        _load_audio(path)


def test_stereo_is_downmixed_to_mono(tmp_path):
    frames = np.array([1000, 3000, 1000, 3000], dtype=np.int16).tobytes()
    path = write_wav(tmp_path / "stereo.wav", channels=2, frames=frames)

    audio = _load_audio(path)

    assert audio is not None
    assert len(audio) == 2
    assert audio[0] == pytest.approx(2000 / 32768, abs=1e-6)
