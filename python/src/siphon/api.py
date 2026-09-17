"""Public entry points: encode_media / encode_media_async."""

from __future__ import annotations

from pathlib import Path

from siphon.cache import UploadCache
from siphon.orchestrator import DEFAULT_SIZE_THRESHOLD, encode_media_sync
from siphon.providers import Provider, get_provider, register_provider
from siphon.sources import MediaSource, from_bytes, from_iterator, from_path

_DEFAULT_CACHE = UploadCache()
_BUILTIN_CLIENT_MODULE_PREFIXES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google.genai",
}


def _ensure_builtin_provider_registered(provider_name: str, client) -> None:
    if provider_name not in _BUILTIN_CLIENT_MODULE_PREFIXES:
        return
    try:
        get_provider(provider_name)
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
    from siphon.orchestrator import encode_media_async as _encode_media_async_impl

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
