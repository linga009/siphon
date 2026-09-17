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

    def inline_size_limit(self) -> int: ...

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
