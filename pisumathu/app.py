"""The daemon: one process that owns the microphone, the hotkey and the UI.

The Tk main loop runs on the main thread. Every other subsystem reports back
through a queue that the main loop drains, so no Tk call ever happens off
the main thread.
"""

from __future__ import annotations

import logging
import os
import queue
import signal
import sys
import threading
import time
import tkinter as tk

from . import __version__, paths, security
from .asr import ModelError, TranscriptionEngine, resolve_model
from .audio import Recorder
from .config import load_config
from .hotkey.factory import create_hotkey
from .hotkey.parser import format_hotkey, parse_hotkey
from .ipc import ControlServer, DaemonLock
from .output.clipboard import Clipboard
from .state import AppState, DictationService

LOG = logging.getLogger("pisumathu")

IDLE_UNLOAD_CHECK_SECONDS = 5.0
MAX_TRANSCRIPTS = 50


def _configure_logging(verbose: bool) -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(paths.log_path(), encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


class Daemon:
    """Owns the whole runtime."""

    def __init__(self) -> None:
        self.config = load_config()
        self.started_at = time.time()
        self.last_activity = time.time()

        self.root: tk.Tk | None = None
        self.pill = None
        self.window = None
        self.tray = None
        self.hotkey = None
        self.recorder: Recorder | None = None
        self.engine: TranscriptionEngine | None = None
        self.clipboard = Clipboard()
        self.service: DictationService | None = None
        self.server: ControlServer | None = None

        self.transcripts: list[str] = []
        self.hotkey_error: str | None = None
        self.audio_error: str | None = None
        self.hotkey_backend = "none"

        self._events: queue.Queue[tuple] = queue.Queue()
        self._shutdown_requested = threading.Event()
        self._closed = False
        self._last_unload_check = time.time()

    # -- lifecycle -----------------------------------------------------

    def run(self) -> int:
        self._build()
        assert self.root is not None
        self._install_signal_handlers()
        self.root.after(50, self._drain_events)
        self.root.after(250, self._check_shutdown)
        self.root.mainloop()
        self._teardown()
        return 0

    def _install_signal_handlers(self) -> None:
        def request(*_args) -> None:
            self._shutdown_requested.set()

        for name in ("SIGINT", "SIGTERM"):
            number = getattr(signal, name, None)
            if number is None:
                continue
            try:
                signal.signal(number, request)
            except (ValueError, OSError):
                pass

    def _build(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("Pisumathu")

        self.recorder = Recorder()
        try:
            self.recorder.start_listener()
        except Exception as exc:  # noqa: BLE001 - reported through status
            self.audio_error = str(exc)
            LOG.error("microphone unavailable: %s", exc)

        try:
            model_path = resolve_model(self.config.model)
        except ModelError:
            model_path = paths.models_dir() / self.config.model

        self.engine = TranscriptionEngine(
            model_name=self.config.model,
            model_path=model_path,
            device=self.config.device,
            compute_type=self.config.compute_type,
            language=self.config.language,
            beam_size=self.config.beam_size,
            vad_filter=self.config.vad_filter,
        )

        self.service = DictationService(
            self.recorder,
            self.engine,
            self.clipboard,
            on_state=self._on_state,
            on_transcript=self._on_transcript,
            auto_clear_seconds=self.config.clipboard_auto_clear_seconds,
        )

        self._build_ui()
        self._start_hotkey()
        self._start_control_server()
        self._start_tray()
        LOG.info(
            "daemon started: model=%s hotkey=%s clipboard=%s",
            self.config.model,
            self.config.hotkey,
            self.clipboard.backend,
        )

    def _build_ui(self) -> None:
        from .ui.main_window import MainWindow
        from .ui.pill import PillOverlay

        assert self.root is not None
        self.pill = PillOverlay(
            self.root,
            on_copy_last=self._copy_last,
            on_clear=self._clear_transcripts,
        )
        self.window = MainWindow(
            self.root,
            self.config,
            on_change_hotkey=self._change_hotkey,
            on_quit=self.request_shutdown,
            on_hide=self._hide_window,
            on_copy_last=self._copy_last,
            on_clear=self._clear_transcripts,
        )
        if self.config.show_window_on_start:
            self.window.show()
        else:
            self.window.hide()

    def _start_hotkey(self) -> None:
        try:
            spec = parse_hotkey(self.config.hotkey)
        except ValueError as exc:
            self.hotkey_error = str(exc)
            LOG.error("invalid hotkey %r: %s", self.config.hotkey, exc)
            return
        try:
            self.hotkey = create_hotkey(spec)
            self.hotkey.start(self._on_hotkey_press, self._on_hotkey_release)
            self.hotkey_backend = self.hotkey.name
            LOG.info("hotkey backend: %s", self.hotkey.name)
        except Exception as exc:  # noqa: BLE001 - daemon stays alive
            self.hotkey_error = str(exc)
            LOG.error("hotkey unavailable: %s", exc)

    def _start_control_server(self) -> None:
        self.server = ControlServer(paths.socket_path(), self._handle_command)
        try:
            self.server.start()
        except Exception as exc:  # noqa: BLE001
            LOG.error("control server failed: %s", exc)
            self.server = None

    def _start_tray(self) -> None:
        """Attach the tray off the critical path.

        pystray can block for several seconds while it negotiates with the
        desktop. Startup and the control channel must not wait for it, or
        ``talk`` reports failure while the daemon is still coming up.
        """

        def work() -> None:
            from .tray import Tray

            tray = Tray(on_show=self._show_window, on_quit=self.request_shutdown)
            if tray.start():
                self.tray = tray
            else:
                LOG.info("tray icon unavailable; continuing without it")

        threading.Thread(target=work, name="tray-start", daemon=True).start()

    # -- hotkey edges --------------------------------------------------

    def _on_hotkey_press(self) -> None:
        self.last_activity = time.time()
        if self.service is not None:
            self.service.press()

    def _on_hotkey_release(self) -> None:
        self.last_activity = time.time()
        if self.service is not None:
            self.service.release()

    # -- callbacks from worker threads ---------------------------------

    def _on_state(self, state: AppState, detail: str) -> None:
        self._events.put(("state", state, detail))

    def _on_transcript(self, text: str) -> None:
        self._events.put(("transcript", text))

    # -- main-thread loop ----------------------------------------------

    def _drain_events(self) -> None:
        if self.root is None:
            return
        try:
            while True:
                event = self._events.get_nowait()
                kind = event[0]
                if kind == "state":
                    _, state, detail = event
                    if self.pill is not None:
                        self.pill.set_state(state, detail)
                    if self.window is not None:
                        self.window.set_state(state, detail)
                elif kind == "transcript":
                    text = event[1]
                    self.transcripts.append(text)
                    del self.transcripts[:-MAX_TRANSCRIPTS]
                    if self.window is not None:
                        self.window.append_transcript(text)
        except queue.Empty:
            pass
        self._maybe_unload_model()
        self.root.after(50, self._drain_events)

    def _maybe_unload_model(self) -> None:
        if self.engine is None or not self.engine.is_loaded:
            return
        if self.config.idle_unload_seconds <= 0:
            return
        now = time.time()
        if now - self._last_unload_check < IDLE_UNLOAD_CHECK_SECONDS:
            return
        self._last_unload_check = now
        idle_for = now - self.last_activity
        if idle_for < self.config.idle_unload_seconds:
            return
        if self.service is not None and self.service.state is not AppState.IDLE:
            return
        LOG.info("unloading model after %.0fs idle", idle_for)
        self.engine.unload()

    def _check_shutdown(self) -> None:
        if self._shutdown_requested.is_set():
            self._shutdown()
            return
        if self.root is not None:
            self.root.after(250, self._check_shutdown)

    # -- commands ------------------------------------------------------

    def request_shutdown(self) -> None:
        self._shutdown_requested.set()

    def _handle_command(self, command: str) -> dict:
        if command == "ping":
            return {"pong": True}
        if command == "status":
            return self.status()
        if command == "stop":
            self.request_shutdown()
            return {"stopping": True}
        raise ValueError(f"unknown command {command!r}")

    def status(self) -> dict:
        state = self.service.state.value if self.service else "starting"
        return {
            "pid": os.getpid(),
            "version": __version__,
            "state": state,
            "uptime_seconds": round(time.time() - self.started_at, 1),
            "model": self.config.model,
            "model_loaded": bool(self.engine and self.engine.is_loaded),
            "device": self.engine.resolved_device if self.engine else self.config.device,
            "device_warning": self.engine.load_warning if self.engine else None,
            "hotkey": format_hotkey(parse_hotkey(self.config.hotkey))
            if _valid_hotkey(self.config.hotkey)
            else self.config.hotkey,
            "hotkey_backend": self.hotkey_backend,
            "hotkey_error": self.hotkey_error,
            "audio_error": self.audio_error,
            "clipboard": self.clipboard.backend,
            "last_error": self.service.last_error if self.service else None,
            "transcripts": len(self.transcripts),
            "last_transcript_length": len(self.transcripts[-1]) if self.transcripts else 0,
        }

    # -- UI actions ----------------------------------------------------

    def _copy_last(self) -> bool:
        if not self.transcripts:
            return False
        return self.clipboard.copy(self.transcripts[-1])

    def _clear_transcripts(self) -> None:
        self.transcripts.clear()
        if self.window is not None:
            self.window.clear_transcripts()

    def _show_window(self) -> None:
        if self.window is not None:
            self.window.show()

    def _hide_window(self) -> None:
        if self.window is not None:
            self.window.hide()

    def _change_hotkey(self, text: str) -> bool:
        try:
            spec = parse_hotkey(text)
        except ValueError as exc:
            if self.window is not None:
                self.window.show_error(str(exc))
            return False

        if self.hotkey is not None:
            self.hotkey.stop()
        try:
            backend = create_hotkey(spec)
            backend.start(self._on_hotkey_press, self._on_hotkey_release)
        except Exception as exc:  # noqa: BLE001
            self.hotkey_error = str(exc)
            if self.window is not None:
                self.window.show_error(f"hotkey failed: {exc}")
            return False

        self.hotkey = backend
        self.hotkey_backend = backend.name
        self.hotkey_error = None
        self.config.hotkey = text.strip()
        from .config import save_config

        save_config(self.config)
        return True

    # -- shutdown ------------------------------------------------------

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        LOG.info("shutting down")
        if self.service is not None:
            self.service.shutdown()
        if self.hotkey is not None:
            try:
                self.hotkey.stop()
            except Exception:  # noqa: BLE001
                pass
        if self.recorder is not None:
            self.recorder.stop_listener()
        if self.engine is not None:
            self.engine.unload()
        if self.server is not None:
            self.server.stop()
        if self.tray is not None:
            self.tray.stop()
        if self.root is not None:
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                pass

    def _teardown(self) -> None:
        self._shutdown()
        security.remove_quietly(paths.socket_path())


def _valid_hotkey(text: str) -> bool:
    try:
        parse_hotkey(text)
    except ValueError:
        return False
    return True


def main() -> int:
    """Start the daemon, or exit quietly if one is already running."""
    lock = DaemonLock(paths.lock_path())
    if not lock.acquire(wait=5.0):
        print("pisumathu is already running", file=sys.stderr)
        return 0

    config = load_config()
    _configure_logging(config.verbose)
    try:
        return Daemon().run()
    except Exception:  # noqa: BLE001 - log the traceback, exit non-zero
        LOG.exception("daemon crashed")
        return 1
    finally:
        lock.release()
