"""
transcription/engine.py — Whisper-based speech-to-text engine.

Handles model loading (with CUDA fallback), transcription, and
exposes a clean synchronous interface to the app controller.
"""

import os
import time
import threading
from typing import Optional, Callable


class TranscriptionEngine:
    """
    Wraps OpenAI Whisper for offline speech-to-text.

    Thread-safe: model is loaded once; transcribe() can be called from
    any thread (it blocks the calling thread while running).
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "cuda",
        language: str = "en",
    ):
        self.model_size = model_size
        self.language = language
        self._model = None
        self._device = device
        self._actual_device: Optional[str] = None
        self._lock = threading.Lock()
        self._ready = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(
        self,
        on_progress: Optional[Callable[[str], None]] = None,
    ) -> bool:
        """
        Load the Whisper model. Call once at startup (blocking).

        Args:
            on_progress: Optional status callback for UI feedback.

        Returns:
            True if load succeeded.
        """
        try:
            import torch
            import whisper

            # Determine device
            if self._device == "cuda" and torch.cuda.is_available():
                self._actual_device = "cuda"
            else:
                self._actual_device = "cpu"
                if self._device == "cuda":
                    print("[Transcription] CUDA unavailable — falling back to CPU.")

            if on_progress:
                on_progress(f"Loading model '{self.model_size}' on {self._actual_device}…")

            self._model = whisper.load_model(
                self.model_size,
                device=self._actual_device,
            )
            self._ready = True

            if on_progress:
                on_progress(f"Model ready on {self._actual_device.upper()}.")

            print(f"[Transcription] Model '{self.model_size}' ready on {self._actual_device}.")
            return True

        except ImportError as e:
            msg = f"[Transcription] Import error: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False
        except Exception as e:
            msg = f"[Transcription] Load failed: {e}"
            print(msg)
            if on_progress:
                on_progress(msg)
            return False

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(self, wav_path: str) -> Optional[str]:
        """
        Transcribe a WAV file and return the text.

        Args:
            wav_path: Path to a 16 kHz mono WAV file.

        Returns:
            Transcribed string, or None on failure.
        """
        if not self._ready or self._model is None:
            print("[Transcription] Model not loaded.")
            return None

        if not os.path.exists(wav_path):
            print(f"[Transcription] File not found: {wav_path}")
            return None

        try:
            with self._lock:
                import torch

                fp16 = self._actual_device == "cuda"
                t0 = time.perf_counter()

                result = self._model.transcribe(
                    wav_path,
                    language=self.language if self.language != "kn" else None,
                    fp16=fp16,
                    temperature=0.0,
                    best_of=1,
                    beam_size=1,
                    condition_on_previous_text=False,
                )

                elapsed = time.perf_counter() - t0
                text = result.get("text", "").strip()
                print(f"[Transcription] Done in {elapsed:.2f}s: '{text[:60]}…'" if len(text) > 60 else f"[Transcription] Done in {elapsed:.2f}s: '{text}'")
                return text

        except Exception as e:
            print(f"[Transcription] Error: {e}")
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def actual_device(self) -> Optional[str]:
        return self._actual_device

    def set_language(self, lang: str) -> None:
        """Hot-swap language without reloading the model."""
        self.language = lang
