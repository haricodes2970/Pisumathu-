"""Device selection and the CPU fallback.

A machine can report a CUDA device and still fail to use it, because the
runtime libraries are a separate install and ctranslate2 only notices at the
first real inference. That must degrade to CPU rather than turn every
dictation into an error.
"""

import sys
import types

import pytest

from pisumathu.asr import engine as engine_module
from pisumathu.asr.engine import TranscriptionEngine
from pisumathu.asr.models import ModelError

CUBLAS_ERROR = "Library libcublas.so.12 is not found or cannot be loaded"


class FakeWhisperModel:
    """Stands in for faster_whisper.WhisperModel.

    ``fail_at`` selects where CUDA breaks: at construction, or at the first
    inference, which is what actually happens on this machine.
    """

    attempts: list[str] = []
    inferences: list[str] = []
    fail_at: str | None = "infer"

    def __init__(self, path, device, **kwargs):
        FakeWhisperModel.attempts.append(device)
        if device == "cuda" and FakeWhisperModel.fail_at == "construct":
            raise RuntimeError(CUBLAS_ERROR)
        self.device = device
        self.path = path

    def transcribe(self, audio, **kwargs):
        FakeWhisperModel.inferences.append(self.device)
        if self.device == "cuda" and FakeWhisperModel.fail_at == "infer":
            raise RuntimeError(CUBLAS_ERROR)
        return iter([]), None


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    FakeWhisperModel.attempts = []
    FakeWhisperModel.inferences = []
    FakeWhisperModel.fail_at = "infer"
    module = types.SimpleNamespace(WhisperModel=FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", module)
    monkeypatch.setattr(engine_module, "verify_model", lambda name: True)
    return FakeWhisperModel


def make_engine(tmp_path, device="auto", resolved="cuda", monkeypatch=None):
    model_dir = tmp_path / "tiny"
    model_dir.mkdir(exist_ok=True)
    engine = TranscriptionEngine("tiny", model_dir, device=device)
    if resolved is not None:
        monkeypatch.setattr(engine, "_resolve_device", lambda: resolved)
    return engine


def test_cuda_that_fails_at_inference_falls_back_to_cpu(tmp_path, fake_faster_whisper, monkeypatch):
    engine = make_engine(tmp_path, monkeypatch=monkeypatch)

    engine.load()

    assert fake_faster_whisper.attempts == ["cuda", "cpu"]
    assert engine.resolved_device == "cpu"
    assert engine.is_loaded
    assert engine.load_warning is not None
    assert "cublas" in engine.load_warning


def test_cuda_that_fails_at_construction_falls_back_to_cpu(
    tmp_path, fake_faster_whisper, monkeypatch
):
    fake_faster_whisper.fail_at = "construct"
    engine = make_engine(tmp_path, monkeypatch=monkeypatch)

    engine.load()

    assert fake_faster_whisper.attempts == ["cuda", "cpu"]
    assert engine.resolved_device == "cpu"
    assert engine.load_warning is not None


def test_a_working_gpu_is_kept(tmp_path, fake_faster_whisper, monkeypatch):
    fake_faster_whisper.fail_at = None
    engine = make_engine(tmp_path, monkeypatch=monkeypatch)

    engine.load()

    assert engine.resolved_device == "cuda"
    assert engine.load_warning is None
    assert fake_faster_whisper.attempts == ["cuda"]


def test_explicit_cuda_does_not_silently_fall_back(tmp_path, fake_faster_whisper, monkeypatch):
    engine = make_engine(tmp_path, device="cuda", resolved=None, monkeypatch=monkeypatch)

    with pytest.raises(ModelError, match="cuda"):
        engine.load()

    assert fake_faster_whisper.attempts == ["cuda"]
    assert not engine.is_loaded


def test_cpu_load_reports_no_warning(tmp_path, fake_faster_whisper, monkeypatch):
    engine = make_engine(tmp_path, device="cpu", resolved=None, monkeypatch=monkeypatch)

    engine.load()

    assert fake_faster_whisper.attempts == ["cpu"]
    assert engine.resolved_device == "cpu"
    assert engine.load_warning is None


def test_unload_clears_the_warning(tmp_path, fake_faster_whisper, monkeypatch):
    engine = make_engine(tmp_path, monkeypatch=monkeypatch)
    engine.load()
    assert engine.load_warning is not None

    engine.unload()

    assert engine.load_warning is None
    assert not engine.is_loaded


def test_load_is_idempotent(tmp_path, fake_faster_whisper, monkeypatch):
    engine = make_engine(tmp_path, device="cpu", resolved=None, monkeypatch=monkeypatch)

    engine.load()
    engine.load()

    assert fake_faster_whisper.attempts == ["cpu"]
