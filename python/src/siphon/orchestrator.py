"""Core decision logic: cache check, size threshold, native upload, inline fallback."""

from __future__ import annotations

import logging
from typing import Iterator

from siphon.base64_stream import encode_chunks_to_base64
from siphon.cache import UploadCache
from siphon.hashing import TeeHasher, hash_chunks
from siphon.providers import Provider
from siphon.sources import MediaSource

logger = logging.getLogger("siphon")

DEFAULT_SIZE_THRESHOLD = 262144


def _inline_block(provider: Provider, chunks: Iterator[bytes], mime_type: str) -> dict:
    b64 = encode_chunks_to_base64(chunks)
    return provider.build_inline_block(b64, mime_type)


def encode_media_sync(
    provider: Provider,
    provider_name: str,
    source: MediaSource,
    cache: UploadCache,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
) -> dict:
    supports_type = provider.supports_media_type(source.mime_type)

    if source.seekable:
        content_hash = hash_chunks(source.chunks())
        cached = cache.get(provider_name, content_hash)
        if cached is not None:
            return provider.build_reference_block(cached, source.mime_type)

        should_go_inline = not supports_type or (
            source.size is not None and source.size < size_threshold
        )
        if should_go_inline:
            return _inline_block(provider, source.chunks(), source.mime_type)

        try:
            ref = provider.upload(source.chunks(), source.mime_type)
        except Exception:
            if not allow_inline_fallback:
                raise
            logger.warning(
                "siphon: native upload to %r failed; falling back to inline base64 "
                "(this reintroduces the size/memory overhead Siphon avoids).",
                provider_name,
                exc_info=True,
            )
            return _inline_block(provider, source.chunks(), source.mime_type)

        cache.put(provider_name, content_hash, ref)
        return provider.build_reference_block(ref, source.mime_type)

    # Non-seekable: no pre-hash, no proactive size-threshold inline path (size may
    # be unknown). Always attempt native upload if the type is supported; hash is
    # computed as a side effect of the single read pass and cached only on success.
    if not supports_type:
        raise ValueError(
            f"{provider_name!r} does not support media type {source.mime_type!r} "
            "and the source is non-seekable, so no inline fallback is possible "
            "(inline encoding would require re-reading the stream from the start)."
        )

    hasher = TeeHasher()

    def _tee() -> Iterator[bytes]:
        for chunk in source.chunks():
            hasher.update(chunk)
            yield chunk

    ref = provider.upload(_tee(), source.mime_type)
    cache.put(provider_name, hasher.hexdigest(), ref)
    return provider.build_reference_block(ref, source.mime_type)
