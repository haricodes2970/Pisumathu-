"""Filesystem and log hygiene.

Recorded speech is sensitive. Everything here exists so that audio is
private, short-lived, and never printed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from . import paths


def ensure_private(path: Path) -> None:
    """Restrict a file to its owner. No-op on Windows, which inherits ACLs."""
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def ensure_private_dir(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass


def secure_audio_path() -> Path:
    """Create a uniquely named, owner-only WAV path inside the runtime dir."""
    directory = paths.runtime_dir()
    ensure_private_dir(directory)
    fd, name = tempfile.mkstemp(prefix="audio-", suffix=".wav", dir=str(directory))
    os.close(fd)
    path = Path(name)
    ensure_private(path)
    return path


def remove_quietly(path: Path | str | None) -> None:
    """Delete a file, ignoring a missing file and permission errors."""
    if not path:
        return
    try:
        Path(path).unlink()
    except (FileNotFoundError, OSError):
        pass


def redact(text: str | None) -> str:
    """Replace transcript content with a length marker for logs."""
    if not text:
        return ""
    return f"<redacted {len(text)} chars>"
