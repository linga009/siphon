"""Streaming content hashing used for cache keys."""

from __future__ import annotations

import hashlib
from typing import Iterable


class TeeHasher:
    """Incrementally hash bytes as they pass through some other pipeline."""

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        self._hasher.update(chunk)

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def hash_chunks(chunks: Iterable[bytes]) -> str:
    """Hash an iterable of byte chunks without concatenating them in memory."""
    hasher = TeeHasher()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.hexdigest()
