import sys

import pytest

from pisumathu.ipc import DaemonLock, DaemonNotRunning, send


def test_lock_is_exclusive(tmp_path):
    path = tmp_path / "daemon.lock"
    first = DaemonLock(path)
    second = DaemonLock(path)

    assert first.acquire() is True
    assert second.acquire() is False
    first.release()
    assert second.acquire() is True
    second.release()


def test_lock_records_pid(tmp_path):
    path = tmp_path / "daemon.lock"
    lock = DaemonLock(path)
    assert lock.acquire() is True
    try:
        assert path.read_text(encoding="utf-8").strip().isdigit()
    finally:
        lock.release()


def test_release_is_idempotent(tmp_path):
    lock = DaemonLock(tmp_path / "daemon.lock")
    lock.acquire()
    lock.release()
    lock.release()


def test_send_to_missing_daemon_raises(tmp_path):
    with pytest.raises(DaemonNotRunning):
        send("status", tmp_path / "nothing.sock", timeout=0.2)


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the POSIX socket")
def test_server_round_trip(tmp_path):
    import time

    from pisumathu.ipc import ControlServer

    path = tmp_path / "control.sock"
    server = ControlServer(path, lambda command: {"echo": command})
    server.start()
    try:
        deadline = time.monotonic() + 2.0
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert send("hello", path) == {"echo": "hello"}
    finally:
        server.stop()
    assert not path.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="exercises the POSIX socket")
def test_server_reports_handler_errors(tmp_path):
    from pisumathu.ipc import ControlServer

    def handler(command: str) -> dict:
        raise ValueError("boom")

    path = tmp_path / "control.sock"
    server = ControlServer(path, handler)
    server.start()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            send("anything", path)
    finally:
        server.stop()
