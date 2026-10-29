"""Model discovery, download, and integrity verification.

Downloads happen only through :func:`download_model`. Loading never touches
the network: the engine receives a local directory and sets
``local_files_only=True``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from .. import paths

MODEL_IDS: dict[str, str] = {
    "tiny": "Systran/faster-whisper-tiny",
    "tiny.en": "Systran/faster-whisper-tiny.en",
    "base": "Systran/faster-whisper-base",
    "base.en": "Systran/faster-whisper-base.en",
    "small": "Systran/faster-whisper-small",
    "small.en": "Systran/faster-whisper-small.en",
    "medium": "Systran/faster-whisper-medium",
    "large-v3": "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
}

DEFAULT_MODEL = "tiny"
MANIFEST_NAME = "manifest.json"
_REQUIRED_FILE = "model.bin"


class ModelError(RuntimeError):
    """Raised when a model is unknown, missing, or fails verification."""


def resolve_model(name: str) -> Path:
    """Return the local directory for a known model name.

    Raises:
        ModelError: if the name is not in :data:`MODEL_IDS`. This also blocks
            path traversal, since only literal known names are accepted.
    """
    if name not in MODEL_IDS:
        raise ModelError(f"unknown model {name!r}; known models: {', '.join(MODEL_IDS)}")
    target = (paths.models_dir() / name).resolve()
    root = paths.models_dir().resolve()
    if root not in target.parents and target != root:
        raise ModelError(f"model path escapes the models directory: {target}")
    return target


def model_available(name: str) -> bool:
    """True when the model directory holds a usable model file."""
    try:
        directory = resolve_model(name)
    except ModelError:
        return False
    return (directory / _REQUIRED_FILE).is_file()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_manifest(directory: Path, name: str) -> Path:
    files = {
        str(p.relative_to(directory)): _sha256(p)
        for p in sorted(directory.rglob("*"))
        if p.is_file() and p.name != MANIFEST_NAME
    }
    manifest = {"name": name, "repo": MODEL_IDS[name], "files": files}
    path = directory / MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def verify_model(name: str) -> bool:
    """Check every file against the manifest written at download time.

    Returns ``False`` when the manifest is missing, unreadable, or any file
    has changed.
    """
    try:
        directory = resolve_model(name)
    except ModelError:
        return False
    manifest_path = directory / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files: dict[str, str] = manifest["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return False

    for relative, expected in files.items():
        target = (directory / relative).resolve()
        if directory.resolve() not in target.parents:
            return False
        if not target.is_file() or _sha256(target) != expected:
            return False
    return True


def download_model(
    name: str,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Fetch a model into the application data directory and record hashes."""
    directory = resolve_model(name)
    directory.mkdir(parents=True, exist_ok=True)

    if progress:
        progress(f"downloading {name} from {MODEL_IDS[name]}")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:
        raise ModelError("huggingface_hub is not installed") from exc

    try:
        snapshot_download(repo_id=MODEL_IDS[name], local_dir=str(directory))
    except Exception as exc:  # noqa: BLE001 - network and auth errors alike
        raise ModelError(f"download failed for {name}: {exc}") from exc

    if not (directory / _REQUIRED_FILE).is_file():
        raise ModelError(f"download for {name} produced no {_REQUIRED_FILE}")

    _write_manifest(directory, name)
    if progress:
        progress(f"verified {name}")
    return directory
