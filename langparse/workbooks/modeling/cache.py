from __future__ import annotations


class MemoryDecisionCache:
    """Process-local storage for response envelopes that passed contract validation."""

    def __init__(self) -> None:
        self._responses: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self._responses.get(key)

    def put(self, key: str, body: bytes) -> None:
        self._responses[key] = bytes(body)
