#!/usr/bin/env python3
"""End-to-end check against the real engine, clipboard and audio pipeline.

This is not a unit test. It needs a downloaded model, a working clipboard
backend and a desktop session, so it is not collected by pytest.

Usage:

    python scripts/e2e_check.py

It synthesises a sentence with espeak-ng, transcribes it through the real
faster-whisper engine, puts the result on the real clipboard, and then drives
a full press/release cycle through ``DictationService`` with a recorder that
replays the file instead of using the microphone.

Everything downstream of capture is the production code path.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pisumathu.asr import TranscriptionEngine, resolve_model, verify_model  # noqa: E402
from pisumathu.audio import Recorder  # noqa: E402
from pisumathu.output.clipboard import Clipboard  # noqa: E402
from pisumathu.state import AppState, DictationService  # noqa: E402

SENTENCE = "hello world this is a test of offline dictation"
MODEL = "tiny"


def make_speech(directory: Path) -> Path:
    """Synthesise the test sentence as 16 kHz mono PCM."""
    raw = directory / "raw.wav"
    final = directory / "speech16k.wav"
    subprocess.run(["espeak-ng", "-w", str(raw), "-s", "150", SENTENCE], check=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw),
            "-ar",
            "16000",
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            str(final),
        ],
        check=True,
    )
    return final


class ReplayRecorder(Recorder):
    """Recorder that replays a WAV file instead of the microphone."""

    def __init__(self, source: Path) -> None:
        super().__init__()
        self.source = source
        self.last_path: Path | None = None

    def start(self) -> bool:
        with wave.open(str(self.source), "rb") as handle:
            data = handle.readframes(handle.getnframes())
        chunk = 2048  # 1024 frames of 16-bit mono
        with self._lock:
            if self._frames is not None:
                return False
            self._frames = [data[i : i + chunk] for i in range(0, len(data), chunk)]
        return True

    def stop(self) -> Path:
        self.last_path = super().stop()
        return self.last_path


def read_clipboard() -> str:
    """Read the clipboard from whichever display-server path answers."""
    commands = [
        ["wl-paste", "--no-newline"],
        ["xsel", "--clipboard", "--output"],
    ]
    for command in commands:
        if not shutil.which(command[0]):
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3)
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


def check(label: str, condition: bool, detail: str = "") -> bool:
    print(f"  [{'PASS' if condition else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    return condition


def main() -> int:
    for tool in ("espeak-ng", "ffmpeg"):
        if not shutil.which(tool):
            print(f"missing required tool: {tool}")
            return 2

    failures = 0

    print("1. model integrity")
    failures += not check(f"{MODEL} verified", verify_model(MODEL))
    if failures:
        print(f"\nRun: talk model download {MODEL}")
        return 1

    with tempfile.TemporaryDirectory(prefix="pisumathu-e2e-") as temp:
        speech = make_speech(Path(temp))
        with wave.open(str(speech), "rb") as handle:
            seconds = handle.getnframes() / handle.getframerate()
        print(f"  synthesized {seconds:.2f}s of speech")

        print("2. engine")
        engine = TranscriptionEngine(MODEL, resolve_model(MODEL), device="cpu", compute_type="int8")
        started = time.monotonic()
        engine.load()
        print(f"  load {time.monotonic() - started:.2f}s")

        started = time.monotonic()
        text = engine.transcribe(speech) or ""
        elapsed = time.monotonic() - started
        print(f"  transcribe {elapsed:.2f}s -> {text!r}")
        failures += not check("transcript is non-empty", bool(text))
        failures += not check("transcript mentions dictation", "dictation" in text.lower())

        print("3. clipboard")
        clipboard = Clipboard()
        print(f"  backend {clipboard.backend}")
        failures += not check("copy accepted", clipboard.copy(text))
        failures += not check("clipboard round trip", read_clipboard().strip() == text.strip())

        print("4. dictation cycle")
        recorder = ReplayRecorder(speech)
        states: list[str] = []
        service = DictationService(
            recorder,
            engine,
            clipboard,
            on_state=lambda state, detail: states.append(state.value),
        )
        clipboard.copy("sentinel-before")
        service.press()
        service.release()
        failures += not check("worker finished", service.wait(timeout=90))
        print(f"  states {' -> '.join(states)}")
        failures += not check("no error", service.last_error is None, str(service.last_error))
        failures += not check("reached copied", AppState.COPIED.value in states)
        failures += not check("clipboard updated", read_clipboard().strip() != "sentinel-before")

        print("5. no recorded audio left behind")
        recorded = recorder.last_path
        failures += not check("a recording was produced", recorded is not None)
        failures += not check(
            "recorded audio deleted",
            recorded is not None and not recorded.exists(),
            str(recorded) if recorded else "",
        )

    print()
    if failures:
        print(f"RESULT: {failures} check(s) failed")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
