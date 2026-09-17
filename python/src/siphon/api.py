"""Public entry points: encode_media / encode_media_async."""

from __future__ import annotations

import logging
from pathlib import Path

from siphon.cache import UploadCache
from siphon.orchestrator import (
    DEFAULT_SIZE_THRESHOLD,
    encode_media_async as _encode_media_async_impl,
    encode_media_sync,
)
from siphon.providers import Provider, get_provider, register_provider
from siphon.sources import MediaSource, from_bytes, from_iterator, from_path

logger = logging.getLogger("siphon")

_DEFAULT_CACHE = UploadCache()
_BUILTIN_PROVIDER_NAMES = frozenset({"openai", "anthropic", "gemini"})

# Tracks which client instance was used to auto-register each built-in provider
# name, so a later call with a *different* client for the same name can be flagged
# instead of silently continuing to use the original client.
_AUTO_REGISTERED_CLIENTS: dict[str, object] = {}


def _ensure_builtin_provider_registered(provider_name: str, client) -> None:
    if provider_name not in _BUILTIN_PROVIDER_NAMES:
        return
    try:
        get_provider(provider_name)
        registered_client = _AUTO_REGISTERED_CLIENTS.get(provider_name)
        if registered_client is not None and client is not registered_client:
            logger.warning(
                "siphon: encode_media() was called with a different client instance "
                "for already-registered provider %r. The client passed on first use "
                "is still the one in effect; this call's client was ignored. If you "
                "intended to switch clients (e.g. a different API key or org), call "
                "siphon.register_provider(%r, ...) explicitly with a new adapter.",
                provider_name,
                provider_name,
            )
        return  # already registered (built-in or user override)
    except KeyError:
        pass

    if provider_name == "openai":
        from siphon.providers.openai_provider import OpenAIProvider

        register_provider("openai", OpenAIProvider(client))
    elif provider_name == "anthropic":
        from siphon.providers.anthropic_provider import AnthropicProvider

        register_provider("anthropic", AnthropicProvider(client))
    elif provider_name == "gemini":
        from siphon.providers.gemini_provider import GeminiProvider

        register_provider("gemini", GeminiProvider(client))
    _AUTO_REGISTERED_CLIENTS[provider_name] = client


def _resolve_source(
    source: str | Path | bytes | MediaSource, mime_type: str | None
) -> MediaSource:
    if isinstance(source, MediaSource):
        return source
    if isinstance(source, bytes):
        if mime_type is None:
            raise ValueError("mime_type is required when source is raw bytes")
        return from_bytes(source, mime_type=mime_type)
    return from_path(source, mime_type=mime_type)


def encode_media(
    client,
    provider_name: str,
    source: str | Path | bytes | MediaSource,
    *,
    mime_type: str | None = None,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
    cache: UploadCache | None = None,
) -> dict:
    _ensure_builtin_provider_registered(provider_name, client)
    provider = get_provider(provider_name)
    media_source = _resolve_source(source, mime_type)
    return encode_media_sync(
        provider,
        provider_name,
        media_source,
        cache or _DEFAULT_CACHE,
        size_threshold=size_threshold,
        allow_inline_fallback=allow_inline_fallback,
    )


async def encode_media_async(
    client,
    provider_name: str,
    source: str | Path | bytes | MediaSource,
    *,
    mime_type: str | None = None,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
    cache: UploadCache | None = None,
) -> dict:
    _ensure_builtin_provider_registered(provider_name, client)
    provider = get_provider(provider_name)
    media_source = _resolve_source(source, mime_type)
    return await _encode_media_async_impl(
        provider,
        provider_name,
        media_source,
        cache or _DEFAULT_CACHE,
        size_threshold=size_threshold,
        allow_inline_fallback=allow_inline_fallback,
    )
