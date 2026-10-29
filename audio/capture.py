from __future__ import annotations

import struct
import wave
import threading
import tempfile
import os
from typing import Optional, Callable

from core.audio_buffer import PreRollBuffer

try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("[Audio] PyAudio not available — capture disabled.")

SAMPLE_RATE = 16_000
CHANNELS = 1
CHUNK = 1024  # ~64 ms at 16 kHz


class AudioCapture:
    """
    Two-phase mic capture with 200 ms pre-roll.

    Phase 1 — Listener (always running after start_listener()):
        Mic stream is kept open. Every chunk feeds PreRollBuffer.
        CPU cost: one PyAudio read + one deque append per 64 ms.

    Phase 2 — Recording (start() / stop()):
        drain() grabs the pre-roll, then new chunks append to _frames.
        stop() finalises the WAV including the pre-roll prefix.

    Thread model:
        _listen_thread  — producer: reads mic, pushes to preroll or frames
        caller thread   — consumer: calls start() / stop()
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        on_level: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.on_level = on_level

        self._preroll = PreRollBuffer(preroll_ms=200, sample_rate=sample_rate)

        self._frames: list[bytes] = []
        self._frames_lock = threading.Lock()

        self._listening = False
        self._recording = False  # guarded by _state_lock
        self._state_lock = threading.Lock()

        self._listen_thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Listener lifecycle  (called once after model ready)
    # ------------------------------------------------------------------

    def start_listener(self) -> None:
        """Open mic stream in background; fill pre-roll continuously."""
        if not PYAUDIO_AVAILABLE:
            return
        with self._state_lock:
            if self._listening:
                return
            self._listening = True

        self._listen_thread = threading.Thread(
            target=self._listen_loop, daemon=True, name="audio-listener"
        )
        self._listen_thread.start()

    def stop_listener(self) -> None:
        with self._state_lock:
            self._listening = False
            self._recording = False

    # ------------------------------------------------------------------
    # Recording API  (called from controller on hotkey press/release)
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Transition listener → recording.
        Drains pre-roll so first word is never truncated.
        """
        with self._state_lock:
            if self._recording:
                return
            preroll = self._preroll.drain()
            with self._frames_lock:
                self._frames = [preroll] if preroll else []
            self._recording = True

        # If listener isn't running yet (e.g. called before start_listener),
        # fall through to legacy one-shot capture mode.
        if not self._listening:
            self.start_listener()

    def stop(self) -> Optional[str]:
        """Stop recording, write WAV, return path."""
        with self._state_lock:
            if not self._recording:
                return None
            self._recording = False

        return self._write_wav()

    def cleanup(self, path: Optional[str]) -> None:
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal — listener loop (single long-lived thread)
    # ------------------------------------------------------------------

    def _listen_loop(self) -> None:
        import pyaudio
        import time

        while self._listening:
            pa = pyaudio.PyAudio()
            try:
                stream = pa.open(
                    format=pyaudio.paInt16,
                    channels=CHANNELS,
                    rate=self.sample_rate,
                    input=True,
                    frames_per_buffer=CHUNK,
                )
                try:
                    while self._listening:
                        try:
                            data = stream.read(CHUNK, exception_on_overflow=False)
                        except OSError:
                            break

                        recording = self._recording
                        if recording:
                            with self._frames_lock:
                                self._frames.append(data)
                            if self.on_level:
                                self.on_level(_compute_rms(data))
                        else:
                            self._preroll.push(data)
                finally:
                    try:
                        stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass
            except Exception as e:
                print(f"[Audio] Stream error: {e} — restarting in 1s")
                time.sleep(1.0)
            finally:
                try:
                    pa.terminate()
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # WAV serialisation
    # ------------------------------------------------------------------

    def _write_wav(self) -> Optional[str]:
        with self._frames_lock:
            frames = list(self._frames)
            self._frames = []

        if not frames:
            return None

        try:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="pisumathu_")
            os.close(fd)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"".join(frames))
            return path
        except OSError as e:
            print(f"[Audio] WAV write failed: {e}")
            return None


def _compute_rms(data: bytes) -> float:
    count = len(data) // 2
    if count == 0:
        return 0.0
    shorts = struct.unpack(f"{count}h", data)
    rms = (sum(s * s for s in shorts) / count) ** 0.5
    return min(rms / 32768.0, 1.0)
