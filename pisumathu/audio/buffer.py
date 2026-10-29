"""Bounded FIFO of audio chunks used as recording pre-roll."""

from __future__ import annotations

from collections import deque


class PreRollBuffer:
    """Keeps the most recent ``capacity_chunks`` chunks.

    The recorder fills this while idle so the first syllable is not clipped
    when the hotkey is pressed.
    """

    def __init__(self, capacity_chunks: int) -> None:
        if capacity_chunks < 0:
            raise ValueError("capacity_chunks must be >= 0")
        self._chunks: deque[bytes] = deque(maxlen=capacity_chunks)

    def push(self, chunk: bytes) -> None:
        self._chunks.append(chunk)

    def drain(self) -> list[bytes]:
        """Return the buffered chunks oldest-first and empty the buffer."""
        items = list(self._chunks)
        self._chunks.clear()
        return items

    def __len__(self) -> int:
        return len(self._chunks)
