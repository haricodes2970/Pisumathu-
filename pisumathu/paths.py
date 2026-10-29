"""Filesystem locations owned by the application.

Everything the app writes lives in one of two directories:

``app_data_dir()``
    Persistent state: config, logs, downloaded models.
``runtime_dir()``
    Transient state: lock file, control socket, recorded audio. Private to
    the user and cleared on logout.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "pisumathu"


def _is_windows() -> bool:
    return sys.platform == "win32"


def app_data_dir() -> Path:
    """Persistent per-user application directory."""
    if _is_windows():
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def runtime_dir() -> Path:
    """Private directory for sockets, locks and recorded audio.

    On Linux this is ``$XDG_RUNTIME_DIR/pisumathu``, which is mode 0700 and
    wiped at logout. Falls back to ``/tmp/pisumathu-<uid>`` only when the
    session runtime directory is unusable.
    """
    if _is_windows():
        path = app_data_dir() / "run"
        path.mkdir(parents=True, exist_ok=True)
        return path

    base = os.environ.get("XDG_RUNTIME_DIR")
    if base and Path(base).is_dir():
        path = Path(base) / APP_NAME
    else:
        uid = os.getuid()
        path = Path(f"/run/user/{uid}") / APP_NAME
        if not path.parent.is_dir():
            path = Path("/tmp") / f"{APP_NAME}-{uid}"

    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


def config_path() -> Path:
    return app_data_dir() / "config.json"


def state_path() -> Path:
    """Small persistent key/value store for setup undo data."""
    return app_data_dir() / "state.json"


def log_path() -> Path:
    return app_data_dir() / "pisumathu.log"


def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def lock_path() -> Path:
    return runtime_dir() / "daemon.lock"


def socket_path() -> Path:
    return runtime_dir() / "daemon.sock"


def port_path() -> Path:
    """Windows control-channel descriptor (port + token)."""
    return runtime_dir() / "daemon.port"
