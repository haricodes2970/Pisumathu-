from __future__ import annotations

import os
import time
import threading
import tempfile
import wave
from typing import Optional, Callable

_WARM_SAMPLES = 16_000  # 1 s silence for CUDA kernel JIT


class TranscriptionEngine:
    """
    faster-whisper engine: large-v3-turbo, GPU int8_float16, CPU int8 fallback.

    Lifecycle:
        load()       — blocking, call once in background thread
        transcribe() — blocking per call, serialised via lock
        set_model_size() — hot-swap while idle (acquires same lock)
    """

    __slots__ = (
        "model_size", "language",
        "_requested_device", "_actual_device", "_actual_compute",
        "_model", "_lock", "_ready",
    )

    def __init__(
        self,
        model_size: str = "large-v3-turbo",
        device: str = "cuda",
        language: str = "en",
    ) -> None:
        self.model_size = model_size
        self.language = language
        self._requested_device = device
        self._actual_device: Optional[str] = None
        self._actual_compute: Optional[str] = None
        self._model = None
        self._lock = threading.Lock()
        self._ready = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, on_progress: Optional[Callable[[str], None]] = None) -> bool:
        try:
            from faster_whisper import WhisperModel

            device, compute_type = self._resolve_device()
            self._actual_device = device
            self._actual_compute = compute_type

            if on_progress:
                on_progress(f"Loading {self.model_size} on {device} ({compute_type})…")

            self._model = WhisperModel(
                self.model_size,
                device=device,
                compute_type=compute_type,
                num_workers=2,
                cpu_threads=4,
            )

            self._warm_start()
            self._ready = True

            msg = f"Model ready — {device.upper()} {compute_type}."
            print(f"[Engine] {msg}")
            if on_progress:
                on_progress(msg)
            return True

        except ImportError as e:
            msg = f"[Engine] Import error: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False
        except Exception as e:
            msg = f"[Engine] Load failed: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(self, wav_path: str) -> Optional[str]:
        if not self._ready or self._model is None:
            print("[Engine] Model not loaded.")
            return None
        if not os.path.exists(wav_path):
            print(f"[Engine] File not found: {wav_path}")
            return None

        try:
            with self._lock:
                t0 = time.perf_counter()

                segments, _ = self._model.transcribe(
                    wav_path,
                    language="en",
                    beam_size=5,
                    best_of=5,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    vad_filter=False,
                    word_timestamps=False,
                    no_speech_threshold=0.3,
                    compression_ratio_threshold=2.4,
                )
                # Materialise generator under lock so no partial reads escape
                text = " ".join(seg.text for seg in segments).strip()
                elapsed = time.perf_counter() - t0

                preview = text[:60] + "…" if len(text) > 60 else text
                print(f"[Engine] {elapsed:.2f}s — '{preview}'")
                return text or None

        except Exception as e:
            print(f"[Engine] Transcription error: {e}")
            return None

    # ------------------------------------------------------------------
    # Runtime mutations
    # ------------------------------------------------------------------

    def set_language(self, lang: str) -> None:
        self.language = lang

    def set_model_size(self, model_size: str) -> bool:
        """Hot-swap model. Acquires inference lock — call from worker thread."""
        with self._lock:
            try:
                from faster_whisper import WhisperModel
                device = self._actual_device or "cpu"
                compute = self._actual_compute or "int8"
                new_model = WhisperModel(
                    model_size,
                    device=device,
                    compute_type=compute,
                    num_workers=2,
                    cpu_threads=4,
                )
                self._model = new_model
                self.model_size = model_size
                print(f"[Engine] Swapped to {model_size}.")
                return True
            except Exception as e:
                print(f"[Engine] Model swap failed: {e}")
                return False

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_device(self) -> tuple[str, str]:
        if self._requested_device != "cuda":
            return "cpu", "int8"
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda", "int8_float16"
            print("[Engine] CUDA unavailable — CPU int8 fallback.")
        except ImportError:
            print("[Engine] torch absent — CPU int8 fallback.")
        return "cpu", "int8"

    def _warm_start(self) -> None:
        """Run 1 s of silence through the decoder to JIT-compile CUDA kernels."""
        try:
            import numpy as np

            samples = np.zeros(_WARM_SAMPLES, dtype=np.int16)
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="_pw_")
            os.close(fd)
            try:
                with wave.open(path, "wb") as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16_000)
                    wf.writeframes(samples.tobytes())
                list(self._model.transcribe(path, language="en")[0])
                print("[Engine] Warm-start done.")
            finally:
                try:
                    os.unlink(path)
                except OSError:
                    pass
        except Exception as e:
            print(f"[Engine] Warm-start skipped: {e}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def actual_device(self) -> Optional[str]:
        return self._actual_device
