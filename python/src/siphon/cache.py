"""In-memory, expiry-aware cache of provider upload references."""

from __future__ import annotations

import time
from typing import Callable

from siphon.providers import ProviderRef


class UploadCache:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._entries: dict[tuple[str, str], ProviderRef] = {}

    def get(self, provider_name: str, content_hash: str) -> ProviderRef | None:
        key = (provider_name, content_hash)
        ref = self._entries.get(key)
        if ref is None:
            return None
        if ref.expires_at is not None and ref.expires_at <= self._clock():
            del self._entries[key]
            return None
        return ref

    def put(self, provider_name: str, content_hash: str, ref: ProviderRef) -> None:
        self._entries[(provider_name, content_hash)] = ref
