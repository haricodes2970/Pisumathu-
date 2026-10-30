"""The ``talk`` command line.

Bare ``talk`` starts the daemon if it is not already running, then prints
its status. Every other subcommand is a thin wrapper over the control
channel or a one-shot filesystem operation.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, paths
from .autostart import get_autostart
from .config import load_config, save_config
from .hotkey.parser import format_hotkey, parse_hotkey
from .ipc import DaemonLock, DaemonNotRunning, send

DAEMON_START_TIMEOUT_SECONDS = 25.0
GSETTINGS_SCHEMA = "org.gnome.desktop.wm.keybindings"
GSETTINGS_KEY = "activate-window-menu"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _is_running() -> bool:
    try:
        send("ping", paths.socket_path(), timeout=1.0)
    except (DaemonNotRunning, RuntimeError, OSError):
        return False
    return True


def _lock_is_free() -> bool:
    """True when no process holds the daemon lock."""
    probe = DaemonLock(paths.lock_path())
    if probe.acquire():
        probe.release()
        return True
    return False


def _spawn_daemon() -> None:
    log_path = paths.log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "ab")
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": handle,
        "stderr": handle,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen([sys.executable, "-m", "pisumathu.daemon"], **kwargs)
    finally:
        handle.close()


def _wait_until_running() -> bool:
    deadline = time.monotonic() + DAEMON_START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _is_running():
            return True
        time.sleep(0.15)
    return False


def _status() -> dict:
    return send("status", paths.socket_path())


def _print_status(data: dict) -> None:
    lines = [
        f"state          {data.get('state')}",
        f"pid            {data.get('pid')}",
        f"uptime         {data.get('uptime_seconds')}s",
        f"model          {data.get('model')}"
        f" ({'loaded' if data.get('model_loaded') else 'not loaded'})",
        f"device         {data.get('device')}",
        f"hotkey         {data.get('hotkey')}  [{data.get('hotkey_backend')}]",
        f"clipboard      {data.get('clipboard')}",
        f"transcripts    {data.get('transcripts')}",
    ]
    for key in ("hotkey_error", "audio_error", "last_error"):
        value = data.get(key)
        if value:
            lines.append(f"{key:<14} {value}")
    print("\n".join(lines))


def _require_daemon() -> bool:
    if _is_running():
        return True
    print("pisumathu is not running; start it with: talk", file=sys.stderr)
    return False


# --------------------------------------------------------------------------
# setup
# --------------------------------------------------------------------------


def _gsettings_get() -> str | None:
    if not shutil.which("gsettings"):
        return None
    try:
        result = subprocess.run(
            ["gsettings", "get", GSETTINGS_SCHEMA, GSETTINGS_KEY],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _gsettings_set(value: str) -> bool:
    try:
        result = subprocess.run(
            ["gsettings", "set", GSETTINGS_SCHEMA, GSETTINGS_KEY, value],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _load_state() -> dict:
    try:
        return json.loads(paths.state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(data: dict) -> None:
    paths.state_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(paths.state_path(), 0o600)
    except OSError:
        pass


def _in_input_group() -> bool:
    if os.name == "nt":
        return True
    try:
        import grp

        group = grp.getgrnam("input")
    except (KeyError, ImportError):
        return False
    return group.gr_gid in os.getgroups() or os.getgid() == group.gr_gid


def _cmd_setup(undo: bool) -> int:
    if sys.platform == "win32":
        print("talk setup is Linux-only; the hotkey needs no system changes on Windows.")
        return EXIT_OK

    state = _load_state()

    if undo:
        original = state.get("alt_space_original")
        if not original:
            print("No saved binding to restore.")
            return EXIT_OK
        if _gsettings_set(original):
            state.pop("alt_space_original", None)
            _save_state(state)
            print(f"Restored Alt+Space to {original}")
            return EXIT_OK
        print("Could not restore the binding with gsettings.", file=sys.stderr)
        return EXIT_ERROR

    current = _gsettings_get()
    if current is None:
        print("gsettings is unavailable; skipping the desktop shortcut release.")
    elif current == "[]":
        print("Alt+Space is already free.")
    else:
        state["alt_space_original"] = current
        _save_state(state)
        if _gsettings_set("[]"):
            print(f"Released the GNOME window-menu shortcut (was {current}).")
            print("Restore it later with: talk setup --undo")
        else:
            print("Could not change the GNOME shortcut.", file=sys.stderr)

    if _in_input_group():
        print("Keyboard access: OK (this user is in the 'input' group).")
    else:
        print("Keyboard access: MISSING.")
        print("  The hotkey needs to read /dev/input/event*. Run:")
        print("    sudo usermod -aG input $USER")
        print("  then log out and back in.")

    return EXIT_OK


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def _cmd_start() -> int:
    if _is_running():
        print("pisumathu is already running.")
        try:
            _print_status(_status())
        except (DaemonNotRunning, RuntimeError) as exc:
            print(f"status unavailable: {exc}", file=sys.stderr)
        return EXIT_OK

    _spawn_daemon()
    if not _wait_until_running():
        # Distinguish "crashed on startup" from "still coming up".
        if _lock_is_free():
            print("pisumathu failed to start. Check the log:", file=sys.stderr)
            print(f"  {paths.log_path()}", file=sys.stderr)
            return EXIT_ERROR
        print(
            "pisumathu is starting but has not answered yet. Check with: talk status",
            file=sys.stderr,
        )
        return EXIT_ERROR

    print("pisumathu started in the background.")
    try:
        _print_status(_status())
    except (DaemonNotRunning, RuntimeError):
        pass
    print("\nHold your hotkey, speak, release. The text lands in the clipboard.")
    return EXIT_OK


def _cmd_status() -> int:
    if not _require_daemon():
        return EXIT_ERROR
    _print_status(_status())
    return EXIT_OK


def _cmd_stop() -> int:
    if not _is_running():
        print("pisumathu is not running.")
        return EXIT_OK
    try:
        send("stop", paths.socket_path())
    except (DaemonNotRunning, RuntimeError) as exc:
        print(f"could not stop the daemon: {exc}", file=sys.stderr)
        return EXIT_ERROR

    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        # The socket stops answering before the process exits and releases the
        # lock. Both must be clear, or the next 'talk' loses the race and dies.
        if not _is_running() and _lock_is_free():
            print("pisumathu stopped.")
            return EXIT_OK
        time.sleep(0.1)
    print("pisumathu did not stop in time.", file=sys.stderr)
    return EXIT_ERROR


def _cmd_config() -> int:
    config = load_config()
    save_config(config)
    print(paths.config_path())
    if shutil.which("xdg-open") and sys.platform != "win32":
        try:
            subprocess.Popen(
                ["xdg-open", str(paths.config_path())],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass
    return EXIT_OK


def _cmd_model_download(name: str) -> int:
    from .asr.models import ModelError, download_model

    def progress(message: str) -> None:
        print(message)

    try:
        path = download_model(name, progress=progress)
    except ModelError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"Model ready at {path}")
    return EXIT_OK


def _cmd_autostart(enable: bool) -> int:
    backend = get_autostart()
    if enable:
        backend.enable()
        print(f"Autostart enabled ({backend.name}).")
    else:
        backend.disable()
        print("Autostart disabled.")
    return EXIT_OK


def _cmd_logs() -> int:
    path = paths.log_path()
    if not path.is_file():
        print("No log file yet.")
        return EXIT_OK
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-50:]))
    return EXIT_OK


def _cmd_version() -> int:
    print(f"pisumathu {__version__}")
    config = load_config()
    try:
        spec = parse_hotkey(config.hotkey)
        hotkey = format_hotkey(spec)
    except ValueError:
        hotkey = config.hotkey
    print(f"hotkey     {hotkey}")
    print(f"model      {config.model}")
    print(f"config     {paths.config_path()}")
    print(f"log        {paths.log_path()}")
    return EXIT_OK


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talk",
        description="Offline push-to-talk dictation. Hold the hotkey, speak, paste.",
    )
    parser.add_argument("--version", action="store_true", help="print version and exit")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="show daemon status")
    subparsers.add_parser("stop", help="stop the daemon")
    subparsers.add_parser("config", help="show and open the config file")
    subparsers.add_parser("logs", help="print the last log lines")
    subparsers.add_parser("version", help="print version and paths")

    setup = subparsers.add_parser("setup", help="release the GNOME Alt+Space shortcut")
    setup.add_argument("--undo", action="store_true", help="restore the shortcut")

    model = subparsers.add_parser("model", help="manage speech models")
    model_sub = model.add_subparsers(dest="model_command")
    download = model_sub.add_parser("download", help="download and verify a model")
    download.add_argument("name", help="tiny, base, small, medium, large-v3, large-v3-turbo")

    autostart = subparsers.add_parser("autostart", help="opt in or out of login autostart")
    autostart_sub = autostart.add_subparsers(dest="autostart_command")
    autostart_sub.add_parser("on", help="start at login")
    autostart_sub.add_parser("off", help="do not start at login")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        return _cmd_version()

    command = args.command
    if command is None:
        return _cmd_start()
    if command == "status":
        return _cmd_status()
    if command == "stop":
        return _cmd_stop()
    if command == "config":
        return _cmd_config()
    if command == "logs":
        return _cmd_logs()
    if command == "version":
        return _cmd_version()
    if command == "setup":
        return _cmd_setup(args.undo)
    if command == "model":
        if args.model_command == "download":
            return _cmd_model_download(args.name)
        parser.parse_args(["model", "--help"])
        return EXIT_USAGE
    if command == "autostart":
        if args.autostart_command == "on":
            return _cmd_autostart(True)
        if args.autostart_command == "off":
            return _cmd_autostart(False)
        parser.parse_args(["autostart", "--help"])
        return EXIT_USAGE

    parser.print_help()
    return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
