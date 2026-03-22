"""
audio/capture.py — Microphone capture using PyAudio.

Records audio in a background thread. Caller starts/stops it and
retrieves the resulting WAV bytes.
"""

import io
import wave
import threading
import tempfile
import os
from typing import Optional, Callable


try:
    import pyaudio
    PYAUDIO_AVAILABLE = True
except ImportError:
    PYAUDIO_AVAILABLE = False
    print("[Audio] PyAudio not available — audio capture disabled.")


# Audio constants
SAMPLE_RATE = 16_000   # Whisper expects 16 kHz
CHANNELS = 1           # Mono
CHUNK = 1024           # Frames per buffer
FORMAT_PA = None       # Set at runtime when pyaudio is imported


class AudioCapture:
    """
    Thread-safe audio recorder.

    Usage:
        cap = AudioCapture()
        cap.start()
        ...user holds key...
        wav_path = cap.stop()  # returns temp file path
        ...transcribe wav_path...
        cap.cleanup(wav_path)
    """

    def __init__(
        self,
        sample_rate: int = SAMPLE_RATE,
        on_level: Optional[Callable[[float], None]] = None,
    ):
        """
        Args:
            sample_rate: Recording sample rate (Hz). Must match Whisper expectation.
            on_level: Optional callback receiving RMS level [0.0 – 1.0] per chunk.
        """
        self.sample_rate = sample_rate
        self.on_level = on_level
        self._pa: Optional["pyaudio.PyAudio"] = None
        self._stream: Optional["pyaudio.Stream"] = None
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._recording = False
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin recording. Non-blocking — spins up a capture thread."""
        if not PYAUDIO_AVAILABLE:
            print("[Audio] PyAudio unavailable, skipping start.")
            return
        if self._recording:
            return

        self._frames = []
        self._recording = True
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._thread.start()

    def stop(self) -> Optional[str]:
        """
        Stop recording and save to a temporary WAV file.

        Returns:
            Path to the WAV file, or None on failure.
        """
        if not self._recording:
            return None
        self._recording = False
        if self._thread:
            self._thread.join(timeout=3.0)
        return self._write_wav()

    def cleanup(self, path: Optional[str]) -> None:
        """Delete a temporary WAV file."""
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _record_loop(self) -> None:
        global FORMAT_PA
        import pyaudio
        FORMAT_PA = pyaudio.paInt16

        self._pa = pyaudio.PyAudio()
        try:
            self._stream = self._pa.open(
                format=FORMAT_PA,
                channels=CHANNELS,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=CHUNK,
            )
            while self._recording:
                try:
                    data = self._stream.read(CHUNK, exception_on_overflow=False)
                    with self._lock:
                        self._frames.append(data)
                    if self.on_level:
                        self.on_level(self._compute_rms(data))
                except OSError:
                    break
        finally:
            if self._stream:
                self._stream.stop_stream()
                self._stream.close()
            self._pa.terminate()
            self._pa = None
            self._stream = None

    def _write_wav(self) -> Optional[str]:
        with self._lock:
            frames = list(self._frames)

        if not frames:
            return None

        try:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="pisumathu_")
            os.close(fd)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # 16-bit = 2 bytes
                wf.setframerate(self.sample_rate)
                wf.writeframes(b"".join(frames))
            return path
        except OSError as e:
            print(f"[Audio] Failed to write WAV: {e}")
            return None

    @staticmethod
    def _compute_rms(data: bytes) -> float:
        """Return normalized RMS energy in [0.0, 1.0]."""
        import struct
        count = len(data) // 2
        if count == 0:
            return 0.0
        shorts = struct.unpack(f"{count}h", data)
        rms = (sum(s * s for s in shorts) / count) ** 0.5
        return min(rms / 32768.0, 1.0)
