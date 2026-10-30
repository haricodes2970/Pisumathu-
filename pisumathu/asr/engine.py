"""faster-whisper wrapper with explicit load/unload.

The model is loaded on demand and dropped after a period of idleness so the
daemon can sit at near-zero memory between dictations.
"""

from __future__ import annotations

import gc
import os
import threading
import wave
from pathlib import Path

import numpy as np

from .models import ModelError, verify_model

DEFAULT_BEAM_SIZE = 1
DEFAULT_VAD = True
SAMPLE_RATE = 16_000


def _load_audio(path: Path) -> np.ndarray | None:
    """Read a 16 kHz mono PCM WAV into float32 samples in [-1, 1].

    faster-whisper normally shells out to PyAV for decoding. We already own
    the recorder, so the file is always PCM we wrote ourselves; decoding it
    here removes a fragile native dependency from the hot path.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            if handle.getframerate() != SAMPLE_RATE:
                raise ValueError(f"expected {SAMPLE_RATE} Hz audio, got {handle.getframerate()} Hz")
            channels = handle.getnchannels()
            width = handle.getsampwidth()
            frames = handle.readframes(handle.getnframes())
    except (OSError, EOFError, wave.Error):
        return None

    if not frames:
        return None
    if width != 2:
        raise ValueError(f"expected 16-bit audio, got {width * 8}-bit")

    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if samples.size == 0:
        return None
    return samples


def _warm_up(model) -> None:  # noqa: ANN001 - faster_whisper.WhisperModel
    """Force one real inference so a broken device fails here, not later.

    ctranslate2 accepts ``device="cuda"`` on a machine that has the driver
    but not cuBLAS, and only raises when it first needs the library. A
    second of silence is enough to prove the device actually computes, which
    keeps ``talk status`` honest and moves the failure to startup.
    """
    segments, _info = model.transcribe(
        np.zeros(SAMPLE_RATE, dtype=np.float32),
        beam_size=1,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    for _segment in segments:
        pass


class TranscriptionEngine:
    """Lazily loaded local speech-to-text engine."""

    def __init__(
        self,
        model_name: str,
        model_path: Path,
        device: str = "auto",
        compute_type: str = "int8",
        language: str | None = None,
        beam_size: int = DEFAULT_BEAM_SIZE,
        vad_filter: bool = DEFAULT_VAD,
    ) -> None:
        self.model_name = model_name
        self.model_path = Path(model_path)
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self._model = None
        self._resolved_device: str | None = None
        self._load_warning: str | None = None
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def resolved_device(self) -> str:
        return self._resolved_device or self.device

    @property
    def load_warning(self) -> str | None:
        """Why the requested device was not used, if it was not."""
        return self._load_warning

    def _resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda"
        except Exception:  # noqa: BLE001 - absence of CUDA is not an error
            pass
        return "cpu"

    def load(self) -> None:
        """Load the model from disk. Idempotent."""
        with self._lock:
            if self._model is not None:
                return
            if not self.model_path.is_dir():
                raise ModelError(
                    f"model {self.model_name!r} is not downloaded; run "
                    f"'talk model download {self.model_name}'"
                )
            if not verify_model(self.model_name):
                raise ModelError(
                    f"model {self.model_name!r} failed integrity verification; "
                    f"re-run 'talk model download {self.model_name}'"
                )

            os.environ.setdefault("HF_HUB_OFFLINE", "1")
            os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

            from faster_whisper import WhisperModel

            device = self._resolve_device()
            # A GPU can be present while its runtime libraries are not: an
            # NVIDIA card with no cuBLAS installed reports a CUDA device and
            # then fails at load. Falling back keeps dictation working instead
            # of turning every press into an error.
            attempts = [device]
            if self.device == "auto" and device != "cpu":
                attempts.append("cpu")

            last_error: Exception | None = None
            for candidate in attempts:
                try:
                    model = WhisperModel(
                        str(self.model_path),
                        device=candidate,
                        compute_type=self.compute_type,
                        local_files_only=True,
                        num_workers=1,
                        cpu_threads=2,
                    )
                    if candidate != "cpu":
                        _warm_up(model)
                except Exception as exc:  # noqa: BLE001 - try the next device
                    last_error = exc
                    continue
                self._model = model
                self._resolved_device = candidate
                self._load_warning = (
                    None
                    if candidate == device
                    else f"{device} unavailable, using {candidate}: {last_error}"
                )
                return

            raise ModelError(f"failed to load model on {device}: {last_error}")

    def unload(self) -> None:
        """Drop the model and release its memory."""
        with self._lock:
            self._model = None
            self._resolved_device = None
            self._load_warning = None
        gc.collect()

    # -- inference ----------------------------------------------------

    def transcribe(self, wav_path: Path) -> str | None:
        """Transcribe a WAV file. Returns ``None`` when nothing was heard."""
        with self._lock:
            model = self._model
        if model is None:
            raise RuntimeError("model is not loaded")

        audio = _load_audio(wav_path)
        if audio is None:
            return None

        segments, _info = model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            best_of=self.beam_size,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=self.vad_filter,
            word_timestamps=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text or None
