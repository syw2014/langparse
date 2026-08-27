from __future__ import annotations

from threading import RLock


class MemoryDecisionCache:
    """Process-local storage for response envelopes that passed contract validation."""

    def __init__(self) -> None:
        self._responses: dict[str, bytes] = {}
        self._lock = RLock()

    def get(self, key: str) -> bytes | None:
        with self._lock:
            return self._responses.get(key)

    def put(self, key: str, body: bytes) -> None:
        copied = bytes(body)
        with self._lock:
            self._responses[key] = copied
