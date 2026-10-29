"""Single-instance enforcement and the CLI↔daemon control channel.

POSIX uses an abstract-free Unix domain socket in the runtime directory.
Windows uses a loopback TCP socket plus a token file, because it has no
reliable AF_UNIX story across the Python versions we support.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path

MAX_MESSAGE_BYTES = 64 * 1024


class DaemonNotRunning(RuntimeError):
    """Raised when no daemon answers the control channel."""


class AlreadyRunning(RuntimeError):
    """Raised when a second daemon tries to start."""


# --------------------------------------------------------------------------
# Lock
# --------------------------------------------------------------------------


class DaemonLock:
    """Advisory, process-scoped lock proving a daemon is running."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._handle = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self) -> bool:
        """Try to take the lock. Returns ``False`` if another process holds it."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+", encoding="utf-8")
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False

        self._handle = handle
        try:
            handle.seek(0)
            handle.truncate()
            handle.write(str(os.getpid()))
            handle.flush()
        except OSError:
            pass
        return True

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            handle.close()


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------


def _read_line(connection: socket.socket) -> bytes:
    buffer = b""
    while len(buffer) < MAX_MESSAGE_BYTES:
        chunk = connection.recv(4096)
        if not chunk:
            break
        buffer += chunk
        if b"\n" in chunk:
            break
    return buffer.split(b"\n", 1)[0]


class _Transport:
    """Platform-specific socket details behind one small interface."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def bind(self) -> socket.socket:
        raise NotImplementedError

    def connect(self, timeout: float) -> socket.socket:
        raise NotImplementedError


class _UnixTransport(_Transport):
    def bind(self) -> socket.socket:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        sock.listen(8)
        return sock

    def connect(self, timeout: float) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(str(self.path))
        return sock


class _TcpTransport(_Transport):
    """Loopback TCP with a shared secret, used on Windows."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._token = ""

    def bind(self) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(8)
        port = sock.getsockname()[1]
        self._token = secrets.token_hex(16)
        self.path.write_text(f"{port}:{self._token}", encoding="utf-8")
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return sock

    def connect(self, timeout: float) -> socket.socket:
        try:
            payload = self.path.read_text(encoding="utf-8").strip()
            port_text, token = payload.split(":", 1)
        except (OSError, ValueError) as exc:
            raise DaemonNotRunning("control channel is not available") from exc
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(("127.0.0.1", int(port_text)))
        sock._pisumathu_token = token  # type: ignore[attr-defined]
        return sock


def _transport(path: Path) -> _Transport:
    return _TcpTransport(path) if sys.platform == "win32" else _UnixTransport(path)


# --------------------------------------------------------------------------
# Server and client
# --------------------------------------------------------------------------


class ControlServer:
    """Accepts JSON-line commands from the CLI and replies with JSON."""

    def __init__(self, path: Path, handler: Callable[[str], dict]) -> None:
        self._transport = _transport(path)
        self._handler = handler
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._socket = self._transport.bind()
        self._socket.settimeout(0.5)
        thread = threading.Thread(target=self._accept_loop, name="control", daemon=True)
        self._thread = thread
        thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        try:
            self._transport.path.unlink()
        except (FileNotFoundError, OSError):
            pass

    def _accept_loop(self) -> None:
        assert self._socket is not None
        while not self._stop.is_set():
            try:
                connection, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                self._serve(connection)
            except Exception:  # noqa: BLE001 - one bad client must not kill the daemon
                pass
            finally:
                try:
                    connection.close()
                except OSError:
                    pass

    def _serve(self, connection: socket.socket) -> None:
        connection.settimeout(2.0)
        raw = _read_line(connection)
        if not raw:
            return
        try:
            request = json.loads(raw.decode("utf-8"))
        except ValueError:
            self._reply(connection, {"ok": False, "error": "malformed request"})
            return

        token = getattr(self._transport, "_token", "")
        if token and request.get("token") != token:
            self._reply(connection, {"ok": False, "error": "bad token"})
            return

        command = request.get("command", "")
        try:
            data = self._handler(command)
        except Exception as exc:  # noqa: BLE001 - reported to the CLI
            self._reply(connection, {"ok": False, "error": str(exc)})
            return
        self._reply(connection, {"ok": True, "data": data})

    @staticmethod
    def _reply(connection: socket.socket, payload: dict) -> None:
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))


def send(command: str, path: Path, timeout: float = 2.0) -> dict:
    """Send a command to the daemon and return its data payload.

    Raises:
        DaemonNotRunning: when nothing is listening.
    """
    transport = _transport(path)
    try:
        connection = transport.connect(timeout)
    except (OSError, DaemonNotRunning) as exc:
        raise DaemonNotRunning("pisumathu daemon is not running") from exc

    try:
        request = {"command": command}
        token = getattr(connection, "_pisumathu_token", "")
        if token:
            request["token"] = token
        connection.sendall((json.dumps(request) + "\n").encode("utf-8"))
        raw = _read_line(connection)
    except OSError as exc:
        raise DaemonNotRunning("pisumathu daemon did not answer") from exc
    finally:
        try:
            connection.close()
        except OSError:
            pass

    if not raw:
        raise DaemonNotRunning("pisumathu daemon closed the connection")
    payload = json.loads(raw.decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "unknown daemon error"))
    return payload.get("data", {})
