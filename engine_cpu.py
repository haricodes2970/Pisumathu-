"""
transcription/engine_cpu.py — faster-whisper CPU backend.

Drop-in replacement for engine.py targeting machines without NVIDIA GPUs.
Uses int8 quantization for speed on CPU.

To use: swap TranscriptionEngine import in core/controller.py.
"""

import os
import time
import threading
from typing import Optional, Callable


class TranscriptionEngineCPU:
    """
    Wraps faster-whisper for offline CPU-based speech-to-text.

    int8 quantization gives 2–4x speedup over raw PyTorch on CPU.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cpu",
        language: str = "en",
    ):
        self.model_size = model_size
        self.language = language
        self._device = device
        self._model = None
        self._lock = threading.Lock()
        self._ready = False

    def load(self, on_progress: Optional[Callable[[str], None]] = None) -> bool:
        try:
            from faster_whisper import WhisperModel

            if on_progress:
                on_progress(f"Loading model '{self.model_size}' (CPU, int8)…")

            self._model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            self._ready = True

            if on_progress:
                on_progress("Model ready on CPU.")

            print(f"[TranscriptionCPU] Model '{self.model_size}' ready (int8).")
            return True

        except ImportError as e:
            msg = f"[TranscriptionCPU] Import error: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False
        except Exception as e:
            msg = f"[TranscriptionCPU] Load failed: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False

    def transcribe(self, wav_path: str) -> Optional[str]:
        if not self._ready or self._model is None:
            return None
        if not os.path.exists(wav_path):
            return None

        try:
            with self._lock:
                t0 = time.perf_counter()
                lang = self.language if self.language != "kn" else None
                segments, _ = self._model.transcribe(
                    wav_path,
                    language=lang,
                    beam_size=1,
                    best_of=1,
                    temperature=0.0,
                )
                text = " ".join(seg.text for seg in segments).strip()
                elapsed = time.perf_counter() - t0
                print(f"[TranscriptionCPU] Done in {elapsed:.2f}s")
                return text
        except Exception as e:
            print(f"[TranscriptionCPU] Error: {e}")
            return None

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def actual_device(self) -> str:
        return "cpu"

    def set_language(self, lang: str) -> None:
        self.language = lang
