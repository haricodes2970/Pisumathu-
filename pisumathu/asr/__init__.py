"""Offline speech-to-text: model management and inference."""

from .engine import TranscriptionEngine
from .models import (
    DEFAULT_MODEL,
    MODEL_IDS,
    ModelError,
    download_model,
    model_available,
    resolve_model,
    verify_model,
)

__all__ = [
    "DEFAULT_MODEL",
    "MODEL_IDS",
    "ModelError",
    "TranscriptionEngine",
    "download_model",
    "model_available",
    "resolve_model",
    "verify_model",
]
