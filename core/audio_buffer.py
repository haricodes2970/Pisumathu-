from __future__ import annotations

import threading
from collections import deque

SAMPLE_RATE: int = 16_000


class PreRollBuffer:
    """
    Thread-safe pre-roll ring buffer (200 ms default).

    Audio chunks are pushed continuously by the mic listener.  At
    speech-start, drain() returns the last <preroll_ms> ms of PCM so
    the first word is never truncated.

    Storage: bounded deque of raw bytes chunks.
    Push: O(1) amortised — append + optional single left-pop.
    Drain: single b"".join, clears in-place.
    """

    __slots__ = ("_max_bytes", "_chunks", "_total_bytes", "_lock")

    def __init__(self, preroll_ms: int = 200, sample_rate: int = SAMPLE_RATE) -> None:
        self._max_bytes: int = int(sample_rate * preroll_ms / 1000) * 2  # int16
        self._chunks: deque[bytes] = deque()
        self._total_bytes: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Hot path — called from audio producer thread every ~64 ms
    # ------------------------------------------------------------------

    def push(self, chunk: bytes) -> None:
        n = len(chunk)
        if n == 0:
            return
        with self._lock:
            self._chunks.append(chunk)
            self._total_bytes += n
            while self._total_bytes > self._max_bytes:
                evicted = self._chunks.popleft()
                self._total_bytes -= len(evicted)

    # ------------------------------------------------------------------
    # Called once at speech-start from recording consumer thread
    # ------------------------------------------------------------------

    def drain(self) -> bytes:
        """Return all buffered PCM and reset. Zero-copy if single chunk."""
        with self._lock:
            if not self._chunks:
                return b""
            data = b"".join(self._chunks)
            self._chunks.clear()
            self._total_bytes = 0
            return data

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._total_bytes = 0
