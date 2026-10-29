"""faster-whisper wrapper with explicit load/unload.

The model is loaded on demand and dropped after a period of idleness so the
daemon can sit at near-zero memory between dictations.
"""

from __future__ import annotations

import gc
import os
import threading
from pathlib import Path

from .models import ModelError, verify_model

DEFAULT_BEAM_SIZE = 1
DEFAULT_VAD = True


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
        self._lock = threading.Lock()

    # -- lifecycle ----------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def resolved_device(self) -> str:
        return self._resolved_device or self.device

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
            try:
                model = WhisperModel(
                    str(self.model_path),
                    device=device,
                    compute_type=self.compute_type,
                    local_files_only=True,
                    num_workers=1,
                    cpu_threads=2,
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                raise ModelError(f"failed to load model on {device}: {exc}") from exc

            self._model = model
            self._resolved_device = device

    def unload(self) -> None:
        """Drop the model and release its memory."""
        with self._lock:
            self._model = None
            self._resolved_device = None
        gc.collect()

    # -- inference ----------------------------------------------------

    def transcribe(self, wav_path: Path) -> str | None:
        """Transcribe a WAV file. Returns ``None`` when nothing was heard."""
        with self._lock:
            model = self._model
        if model is None:
            raise RuntimeError("model is not loaded")

        segments, _info = model.transcribe(
            str(wav_path),
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
