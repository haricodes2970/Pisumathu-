"""Microphone capture.

A stream is opened once and stays open for the life of the daemon. While
idle, chunks feed a pre-roll buffer; while recording, they accumulate. On
stop, the frames are written to an owner-only WAV in the runtime directory.
"""

from __future__ import annotations

import threading
import wave
from pathlib import Path

from .. import security
from .buffer import PreRollBuffer

SAMPLE_RATE = 16_000
CHANNELS = 1
BLOCKSIZE = 1024
PREROLL_MS = 200


class Recorder:
    """Push-to-talk recorder backed by ``sounddevice``."""

    def __init__(
        self,
        samplerate: int = SAMPLE_RATE,
        channels: int = CHANNELS,
        blocksize: int = BLOCKSIZE,
        preroll_ms: int = PREROLL_MS,
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.blocksize = blocksize
        capacity = max(1, (preroll_ms * samplerate // 1000) // blocksize)
        self._preroll = PreRollBuffer(capacity)
        self._frames: list[bytes] | None = None
        self._stream = None
        self._lock = threading.Lock()
        self._error: str | None = None

    # -- listener -----------------------------------------------------

    def start_listener(self) -> None:
        """Open the microphone stream and start filling the pre-roll."""
        if self._stream is not None:
            return
        try:
            import sounddevice as sd
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._error = f"sounddevice unavailable: {exc}"
            raise RuntimeError(self._error) from exc

        try:
            stream = sd.InputStream(
                samplerate=self.samplerate,
                channels=self.channels,
                dtype="int16",
                blocksize=self.blocksize,
                callback=self._callback,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self._error = f"cannot open microphone: {exc}"
            raise RuntimeError(self._error) from exc

        self._stream = stream
        self._error = None

    def stop_listener(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:  # noqa: BLE001 - shutdown must not raise
            pass

    def _callback(self, indata, frames, time_info, status) -> None:  # noqa: ANN001
        data = bytes(indata)
        with self._lock:
            if self._frames is not None:
                self._frames.append(data)
            else:
                self._preroll.push(data)

    # -- recording ----------------------------------------------------

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._frames is not None

    @property
    def error(self) -> str | None:
        return self._error

    def start(self) -> bool:
        """Begin recording. Returns ``False`` if already recording."""
        with self._lock:
            if self._frames is not None:
                return False
            self._frames = self._preroll.drain()
            return True

    def stop(self) -> Path:
        """Finish recording and write the WAV. Raises if not recording."""
        with self._lock:
            frames = self._frames
            self._frames = None
        if frames is None:
            raise RuntimeError("recorder is not recording")

        path = security.secure_audio_path()
        try:
            with wave.open(str(path), "wb") as handle:
                handle.setnchannels(self.channels)
                handle.setsampwidth(2)
                handle.setframerate(self.samplerate)
                handle.writeframes(b"".join(frames))
        except Exception:
            security.remove_quietly(path)
            raise
        return path

    def cancel(self) -> None:
        """Drop the in-progress recording without writing anything."""
        with self._lock:
            self._frames = None
