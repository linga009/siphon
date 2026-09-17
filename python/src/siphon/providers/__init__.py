"""Provider protocol, reference type, and the provider registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Protocol, runtime_checkable


@dataclass
class ProviderRef:
    id: str
    expires_at: float | None


@runtime_checkable
class Provider(Protocol):
    def supports_media_type(self, mime_type: str) -> bool: ...

    def inline_size_limit(self) -> int:
        """Maximum source size in bytes this provider accepts on the inline
        base64 path. Return a positive integer for a genuine cap; the
        orchestrator raises ValueError if a source routed onto the inline
        path exceeds it. Return 0 (or any non-positive value) if the
        provider has no fixed inline size convention to declare -- this is
        treated as "no declared limit", NOT as "zero bytes allowed", and the
        orchestrator skips the inline-size check entirely in that case.
        """
        ...

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef: ...

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef: ...

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict: ...

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict: ...


_REGISTRY: dict[str, Provider] = {}


def register_provider(name: str, provider: Provider) -> None:
    _REGISTRY[name] = provider


def get_provider(name: str) -> Provider:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown-provider: {name!r} is not registered. "
            f"Known providers: {sorted(_REGISTRY)!r}. "
            "Register a custom provider with siphon.register_provider()."
        ) from None
