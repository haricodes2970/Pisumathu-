import time
from pathlib import Path

import pytest

from pisumathu import security
from pisumathu.state import AppState, DictationService


class FakeRecorder:
    def __init__(self, fail_start: bool = False, fail_stop: bool = False) -> None:
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.starts = 0
        self.stops = 0
        self.cancelled = 0
        self.recording = False
        self._path: Path | None = None

    def start(self) -> bool:
        self.starts += 1
        if self.fail_start:
            raise RuntimeError("no microphone")
        self.recording = True
        return True

    def stop(self) -> Path:
        self.stops += 1
        self.recording = False
        if self.fail_stop:
            raise RuntimeError("device disappeared")
        self._path = security.secure_audio_path()
        self._path.write_bytes(b"RIFF....WAVE")
        return self._path

    def cancel(self) -> None:
        self.cancelled += 1
        self.recording = False

    @property
    def last_path(self) -> Path | None:
        return self._path


class FakeEngine:
    def __init__(self, text: str | None = "hello world", fail_load: bool = False) -> None:
        self.text = text
        self.fail_load = fail_load
        self.is_loaded = False
        self.loads = 0
        self.transcribed: list[Path] = []

    def load(self) -> None:
        self.loads += 1
        if self.fail_load:
            raise RuntimeError("model missing")
        self.is_loaded = True

    def unload(self) -> None:
        self.is_loaded = False

    def transcribe(self, wav_path: Path) -> str | None:
        self.transcribed.append(wav_path)
        return self.text


class FakeClipboard:
    def __init__(self, ok: bool = True) -> None:
        self.ok = ok
        self.copied: list[str] = []
        self.cleared = 0

    def copy(self, text: str) -> bool:
        self.copied.append(text)
        return self.ok

    def clear(self) -> bool:
        self.cleared += 1
        return True


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def build(runtime, **kwargs):
    recorder = kwargs.pop("recorder", FakeRecorder())
    engine = kwargs.pop("engine", FakeEngine())
    clipboard = kwargs.pop("clipboard", FakeClipboard())
    states: list[AppState] = []
    transcripts: list[str] = []

    service = DictationService(
        recorder,
        engine,
        clipboard,
        on_state=lambda state, detail: states.append(state),
        on_transcript=transcripts.append,
        copied_hold=0.02,
        error_hold=0.02,
        **kwargs,
    )
    return service, recorder, engine, clipboard, states, transcripts


def test_press_starts_recording(runtime):
    service, recorder, *_ = build(runtime)
    assert service.press() is True
    assert service.state is AppState.RECORDING
    assert recorder.starts == 1


def test_press_ignored_while_recording(runtime):
    service, recorder, *_ = build(runtime)
    service.press()
    assert service.press() is False
    assert recorder.starts == 1


def test_release_transcribes_and_copies(runtime):
    service, recorder, engine, clipboard, states, transcripts = build(runtime)
    service.press()
    assert service.release() is True
    assert service.wait() is True

    assert clipboard.copied == ["hello world"]
    assert transcripts == ["hello world"]
    assert AppState.TRANSCRIBING in states
    assert AppState.COPIED in states
    assert service.wait_for(AppState.IDLE) is True


def test_empty_transcript_is_an_error(runtime):
    service, _, engine, clipboard, states, _ = build(runtime, engine=FakeEngine(text=""))
    service.press()
    service.release()
    service.wait()

    assert clipboard.copied == []
    assert AppState.ERROR in states
    assert service.last_error == "no speech detected"


def test_none_transcript_is_an_error(runtime):
    service, _, _, clipboard, states, _ = build(runtime, engine=FakeEngine(text=None))
    service.press()
    service.release()
    service.wait()

    assert clipboard.copied == []
    assert AppState.ERROR in states


def test_clipboard_failure_is_an_error(runtime):
    service, _, _, clipboard, states, _ = build(runtime, clipboard=FakeClipboard(ok=False))
    service.press()
    service.release()
    service.wait()

    assert AppState.ERROR in states
    assert service.last_error == "clipboard unavailable"


def test_recorder_start_failure_is_an_error(runtime):
    service, _, _, _, states, _ = build(runtime, recorder=FakeRecorder(fail_start=True))
    assert service.press() is False
    assert AppState.ERROR in states
    assert "no microphone" in (service.last_error or "")


def test_wav_deleted_after_success(runtime):
    service, recorder, *_ = build(runtime)
    service.press()
    service.release()
    service.wait()

    path = recorder.last_path
    assert path is not None
    assert not path.exists()


def test_wav_deleted_when_transcription_raises(runtime):
    class ExplodingEngine(FakeEngine):
        def transcribe(self, wav_path):
            raise RuntimeError("inference blew up")

    service, recorder, *_ = build(runtime, engine=ExplodingEngine())
    service.press()
    service.release()
    service.wait()

    assert recorder.last_path is not None
    assert not recorder.last_path.exists()
    assert service.state is AppState.ERROR


def test_release_without_press_is_ignored(runtime):
    service, recorder, *_ = build(runtime)
    assert service.release() is False
    assert recorder.stops == 0


def test_press_ignored_while_transcribing(runtime):
    service, recorder, *_ = build(runtime)
    service.press()
    service.release()
    assert service.press() is False
    service.wait()


def test_model_prefetch_happens_on_press(runtime):
    service, _, engine, *_ = build(runtime)
    service.press()
    deadline = time.monotonic() + 1.0
    while not engine.is_loaded and time.monotonic() < deadline:
        time.sleep(0.005)
    assert engine.is_loaded is True


def test_auto_clear_schedules_clipboard_clear(runtime):
    service, _, _, clipboard, *_ = build(runtime, auto_clear_seconds=1)
    service.press()
    service.release()
    service.wait()
    deadline = time.monotonic() + 2.0
    while clipboard.cleared == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert clipboard.cleared == 1


def test_shutdown_cancels_recording(runtime):
    service, recorder, *_ = build(runtime)
    service.press()
    service.shutdown()
    assert recorder.cancelled == 1
    assert service.press() is False
