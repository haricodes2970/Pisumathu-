"""Model discovery, download, and integrity verification.

Downloads happen only through :func:`download_model`. Loading never touches
the network: the engine receives a local directory and sets
``local_files_only=True``.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import socket
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .. import paths

HF_API = "https://huggingface.co/api/models"
HF_RESOLVE = "https://huggingface.co/{repo}/resolve/main/{path}"
USER_AGENT = "pisumathu/1.0 (+https://github.com/haricodes2970/Pisumathu-)"
DOWNLOAD_CHUNK = 1024 * 1024

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


def _write_manifest(directory: Path, name: str, hashes: dict[str, str] | None = None) -> Path:
    if hashes is None:
        hashes = {
            str(p.relative_to(directory)): _sha256(p)
            for p in sorted(directory.rglob("*"))
            if p.is_file() and p.name != MANIFEST_NAME
        }
    manifest = {"name": name, "repo": MODEL_IDS[name], "files": hashes}
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


@contextlib.contextmanager
def _prefer_ipv4():
    """Resolve to IPv4 addresses first for the duration of a download.

    On hosts with an IPv6 address but no working IPv6 route, Python's
    ``getaddrinfo`` returns AAAA records first and ``urlopen`` blocks until
    the connection times out, while ``curl`` falls back to IPv4 instantly.
    Preferring IPv4 avoids a multi-minute stall on first download.
    """
    original = socket.getaddrinfo

    def ipv4_first(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        results = original(host, port, family, type, proto, flags)
        ipv4 = [entry for entry in results if entry[0] == socket.AF_INET]
        return ipv4 or results

    socket.getaddrinfo = ipv4_first
    try:
        yield
    finally:
        socket.getaddrinfo = original


def _fetch_json(url: str, timeout: float = 30.0) -> object:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _prefer_ipv4(), urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _download_file(
    url: str,
    destination: Path,
    expected_sha256: str | None,
    progress: Callable[[str], None] | None,
    label: str,
) -> str:
    """Download one file and return its SHA256, verifying the remote hash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    with _prefer_ipv4(), urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        written = 0
        with destination.open("wb") as handle:
            while True:
                block = response.read(DOWNLOAD_CHUNK)
                if not block:
                    break
                handle.write(block)
                digest.update(block)
                written += len(block)
                if progress and total:
                    progress(f"  {label}  {written * 100 // total}%")

    actual = digest.hexdigest()
    if expected_sha256 and actual != expected_sha256:
        destination.unlink(missing_ok=True)
        raise ModelError(f"checksum mismatch for {label}: expected {expected_sha256}, got {actual}")
    return actual


def download_model(
    name: str,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """Fetch a model into the application data directory and record hashes.

    Every file is verified against the SHA256 the Hugging Face API reports,
    so a truncated or tampered transfer is rejected rather than loaded.
    """
    directory = resolve_model(name)
    directory.mkdir(parents=True, exist_ok=True)
    repo = MODEL_IDS[name]

    if progress:
        progress(f"listing {repo}")

    try:
        tree = _fetch_json(f"{HF_API}/{repo}/tree/main")
    except (urllib.error.URLError, ValueError, OSError) as exc:
        raise ModelError(f"cannot reach Hugging Face: {exc}") from exc
    if not isinstance(tree, list):
        raise ModelError(f"unexpected listing for {repo}")

    hashes: dict[str, str] = {}
    for entry in tree:
        if not isinstance(entry, dict) or entry.get("type") != "file":
            continue
        relative = entry.get("path")
        if not relative:
            continue
        # Reject anything that would escape the model directory.
        target = (directory / relative).resolve()
        if directory.resolve() not in target.parents:
            raise ModelError(f"refusing suspicious path {relative!r}")

        expected = (entry.get("lfs") or {}).get("oid")
        if progress:
            progress(f"fetching {relative}")
        try:
            hashes[relative] = _download_file(
                HF_RESOLVE.format(repo=repo, path=relative),
                target,
                expected,
                progress,
                relative,
            )
        except (urllib.error.URLError, OSError) as exc:
            raise ModelError(f"download failed for {relative}: {exc}") from exc

    if not (directory / _REQUIRED_FILE).is_file():
        raise ModelError(f"download for {name} produced no {_REQUIRED_FILE}")

    _write_manifest(directory, name, hashes)
    if progress:
        progress(f"verified {name}")
    return directory
