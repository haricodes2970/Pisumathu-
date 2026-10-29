"""User configuration.

The file is JSON, owner-only, and written atomically. A corrupt or missing
file is never fatal: the defaults are used and the app keeps working.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from . import paths, security


@dataclass
class Config:
    """All user-tunable settings."""

    hotkey: str = "alt+space"
    model: str = "tiny"
    device: str = "auto"
    compute_type: str = "int8"
    language: str | None = None
    beam_size: int = 1
    vad_filter: bool = True
    clipboard_auto_clear_seconds: int = 0
    idle_unload_seconds: int = 300
    show_pill: bool = True
    show_window_on_start: bool = False
    autostart: bool = False
    verbose: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_FIELD_TYPES = {f.name: f.type for f in fields(Config)}


def _coerce(name: str, value: Any, default: Any) -> Any:
    """Return ``value`` if it matches the field's type, else ``default``."""
    if name == "language":
        if value is None:
            return None
        return value if isinstance(value, str) and value.strip() else default
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            return default
        return value
    if isinstance(default, str):
        return value if isinstance(value, str) and value else default
    return value


def load_config(path: Path | None = None) -> Config:
    """Load settings, falling back to defaults for anything unreadable."""
    target = Path(path) if path is not None else paths.config_path()
    config = Config()
    try:
        raw = target.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (FileNotFoundError, OSError, ValueError):
        return config
    if not isinstance(data, dict):
        return config

    for field in fields(Config):
        if field.name not in data:
            continue
        default = getattr(config, field.name)
        setattr(config, field.name, _coerce(field.name, data[field.name], default))
    return config


def save_config(config: Config, path: Path | None = None) -> None:
    """Write settings atomically with owner-only permissions."""
    target = Path(path) if path is not None else paths.config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config.to_dict(), indent=2, sort_keys=True) + "\n"

    fd, tmp_name = tempfile.mkstemp(
        prefix=".config-", suffix=".json", dir=str(target.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        security.ensure_private(tmp)
        os.replace(tmp, target)
    finally:
        security.remove_quietly(tmp)
    security.ensure_private(target)
