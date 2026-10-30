"""Dictation state machine.

Owns the press/release cycle and the worker that turns a recording into
clipboard text. Depends only on the interfaces passed in, so it can be
tested with fakes and has no platform knowledge.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from enum import Enum

from . import security

COPIED_HOLD_SECONDS = 1.2
ERROR_HOLD_SECONDS = 3.0


# str+Enum rather than StrEnum keeps the 3.10 floor intact.
class AppState(str, Enum):  # noqa: UP042
    LOADING = "loading"
    IDLE = "idle"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    COPIED = "copied"
    ERROR = "error"
    UNAVAILABLE = "unavailable"


StateCallback = Callable[[AppState, str], None]
TranscriptCallback = Callable[[str], None]


class DictationService:
    """Coordinates recorder, engine and clipboard for one dictation cycle."""

    def __init__(
        self,
        recorder,
        engine,
        clipboard,
        on_state: StateCallback | None = None,
        on_transcript: TranscriptCallback | None = None,
        auto_clear_seconds: int = 0,
        copied_hold: float = COPIED_HOLD_SECONDS,
        error_hold: float = ERROR_HOLD_SECONDS,
    ) -> None:
        self._recorder = recorder
        self._engine = engine
        self._clipboard = clipboard
        self._on_state = on_state
        self._on_transcript = on_transcript
        self._auto_clear_seconds = auto_clear_seconds
        self._copied_hold = copied_hold
        self._error_hold = error_hold

        self._lock = threading.Lock()
        self._state = AppState.IDLE
        self._detail = ""
        self._last_error: str | None = None
        self._worker: threading.Thread | None = None
        self._timers: list[threading.Timer] = []
        self._closed = False

    # -- observation ---------------------------------------------------

    @property
    def state(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def detail(self) -> str:
        with self._lock:
            return self._detail

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def wait(self, timeout: float = 5.0) -> bool:
        """Block until the in-flight worker finishes. Returns False on timeout."""
        with self._lock:
            worker = self._worker
        if worker is None:
            return True
        worker.join(timeout)
        return not worker.is_alive()

    def wait_for(self, state: AppState, timeout: float = 5.0) -> bool:
        """Poll until ``state`` is reached. Test helper and CLI helper."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.state is state:
                return True
            time.sleep(0.005)
        return self.state is state

    # -- transitions ---------------------------------------------------

    def _set_state(self, state: AppState, detail: str = "") -> None:
        with self._lock:
            self._state = state
            self._detail = detail
        if self._on_state is not None:
            try:
                self._on_state(state, detail)
            except Exception:  # noqa: BLE001 - a broken UI must not stop dictation
                pass

    def _schedule(self, delay: float, action: Callable[[], None]) -> None:
        timer = threading.Timer(delay, action)
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()

    def _return_to_idle(self) -> None:
        with self._lock:
            if self._state in (AppState.COPIED, AppState.ERROR):
                self._state = AppState.IDLE
                self._detail = ""
                should_emit = True
            else:
                should_emit = False
        if should_emit:
            if self._on_state is not None:
                try:
                    self._on_state(AppState.IDLE, "")
                except Exception:  # noqa: BLE001
                    pass

    def _fail(self, message: str) -> None:
        self._last_error = message
        self._set_state(AppState.ERROR, message)
        self._schedule(self._error_hold, self._return_to_idle)

    # -- hotkey edges --------------------------------------------------

    def press(self) -> bool:
        """Begin recording. Ignored unless the service is idle."""
        if self._closed:
            return False
        with self._lock:
            if self._state is not AppState.IDLE:
                return False
            self._state = AppState.RECORDING
            self._detail = ""
        self._emit_state(AppState.RECORDING)

        try:
            started = self._recorder.start()
        except Exception as exc:  # noqa: BLE001 - surfaced as ERROR
            self._fail(f"cannot start recording: {exc}")
            return False
        if not started:
            self._fail("microphone is busy")
            return False

        self._prefetch_model()
        return True

    def release(self) -> bool:
        """Stop recording and transcribe. Ignored unless recording."""
        if self._closed:
            return False
        with self._lock:
            if self._state is not AppState.RECORDING:
                return False
            self._state = AppState.TRANSCRIBING
            self._detail = ""
            worker = threading.Thread(target=self._finish, name="dictation", daemon=True)
            self._worker = worker
        self._emit_state(AppState.TRANSCRIBING)
        worker.start()
        return True

    def _emit_state(self, state: AppState, detail: str = "") -> None:
        if self._on_state is not None:
            try:
                self._on_state(state, detail)
            except Exception:  # noqa: BLE001
                pass

    def _prefetch_model(self) -> None:
        """Load the model in the background while the user speaks."""

        def load() -> None:
            try:
                self._engine.load()
            except Exception:  # noqa: BLE001 - the worker reports the failure
                pass

        if getattr(self._engine, "is_loaded", False):
            return
        threading.Thread(target=load, name="model-prefetch", daemon=True).start()

    # -- worker --------------------------------------------------------

    def _finish(self) -> None:
        wav_path = None
        try:
            wav_path = self._recorder.stop()
            self._engine.load()
            text = self._engine.transcribe(wav_path)

            if not text or not text.strip():
                self._fail("no speech detected")
                return

            if not self._clipboard.copy(text):
                self._fail("clipboard unavailable")
                return

            self._set_state(AppState.COPIED, text)
            if self._on_transcript is not None:
                try:
                    self._on_transcript(text)
                except Exception:  # noqa: BLE001
                    pass
            if self._auto_clear_seconds > 0:
                self._schedule(self._auto_clear_seconds, self._clear_clipboard)
            self._schedule(self._copied_hold, self._return_to_idle)
        except Exception as exc:  # noqa: BLE001 - report, never crash the daemon
            self._fail(str(exc) or exc.__class__.__name__)
        finally:
            security.remove_quietly(wav_path)
            with self._lock:
                self._worker = None

    def _clear_clipboard(self) -> None:
        clear = getattr(self._clipboard, "clear", None)
        if callable(clear):
            try:
                clear()
            except Exception:  # noqa: BLE001
                pass

    # -- shutdown ------------------------------------------------------

    def shutdown(self) -> None:
        """Stop accepting input and release resources."""
        self._closed = True
        with self._lock:
            timers = list(self._timers)
            self._timers.clear()
        for timer in timers:
            timer.cancel()
        try:
            self._recorder.cancel()
        except Exception:  # noqa: BLE001
            pass
        self.wait(timeout=5.0)
