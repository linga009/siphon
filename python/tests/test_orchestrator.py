import logging

import pytest

from siphon.cache import UploadCache
from siphon.hashing import hash_chunks
from siphon.orchestrator import encode_media_async, encode_media_sync
from siphon.providers import ProviderRef
from siphon.sources import from_bytes, from_iterator


class _RecordingProvider:
    def __init__(self, supports=True, raise_on_upload=False):
        self.supports = supports
        self.raise_on_upload = raise_on_upload
        self.upload_calls = 0
        self.uploaded_bytes = b""

    def supports_media_type(self, mime_type: str) -> bool:
        return self.supports

    def inline_size_limit(self) -> int:
        return 10_000_000

    def upload(self, chunks, mime_type: str) -> ProviderRef:
        self.upload_calls += 1
        data = b"".join(chunks)
        self.uploaded_bytes += data
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        return ProviderRef(id=f"ref-{self.upload_calls}", expires_at=None)

    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        raise NotImplementedError

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "ref", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "inline", "data": base64_data}


def test_small_seekable_source_goes_inline_without_calling_upload():
    provider = _RecordingProvider()
    cache = UploadCache()
    source = from_bytes(b"tiny", mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


def test_large_seekable_source_uploads_and_caches():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"x" * 2000
    source = from_bytes(content, mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.upload_calls == 1
    assert provider.uploaded_bytes == content


def test_second_call_with_same_content_hits_cache_and_does_not_reupload():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"y" * 2000

    block1 = encode_media_sync(
        provider, "fake", from_bytes(content, mime_type="image/png"), cache, size_threshold=1000
    )
    block2 = encode_media_sync(
        provider, "fake", from_bytes(content, mime_type="image/png"), cache, size_threshold=1000
    )

    assert block1 == block2
    assert provider.upload_calls == 1


def test_unsupported_media_type_goes_inline_even_if_large():
    provider = _RecordingProvider(supports=False)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="application/weird")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


def test_upload_failure_falls_back_to_inline_with_warning(caplog):
    provider = _RecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    with caplog.at_level(logging.WARNING, logger="siphon"):
        block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    matching_records = [
        record
        for record in caplog.records
        if record.name == "siphon" and record.levelno == logging.WARNING
    ]
    assert any(
        "upload failed" in record.message.lower() or "fall" in record.message.lower()
        for record in matching_records
    )


def test_upload_failure_reraises_when_fallback_disabled():
    provider = _RecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    with pytest.raises(RuntimeError, match="upload failed"):
        encode_media_sync(
            provider, "fake", source, cache, size_threshold=1000, allow_inline_fallback=False
        )


def test_non_seekable_large_source_uploads_and_populates_cache_after_success():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"z" * 5000
    chunks = [content[i : i + 100] for i in range(0, len(content), 100)]
    source = from_iterator(iter(chunks), mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.uploaded_bytes == content

    expected_hash = hash_chunks(iter(chunks))
    cached = cache.get("fake", expected_hash)
    assert cached is not None
    assert cached.id == "ref-1"


def test_non_seekable_upload_failure_reraises_even_with_fallback_allowed():
    provider = _RecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    content = b"w" * 5000
    chunks = [content[i : i + 100] for i in range(0, len(content), 100)]
    source = from_iterator(iter(chunks), mime_type="image/png")

    with pytest.raises(RuntimeError, match="upload failed"):
        encode_media_sync(
            provider, "fake", source, cache, size_threshold=1000, allow_inline_fallback=True
        )


class _TinyInlineLimitProvider(_RecordingProvider):
    """A provider whose inline_size_limit is smaller than the size_threshold used in
    the test, so a source can be routed onto the inline path (size < size_threshold)
    while still exceeding what this provider can actually accept inline."""

    def inline_size_limit(self) -> int:
        return 100


def test_inline_path_raises_when_source_exceeds_providers_inline_size_limit():
    provider = _TinyInlineLimitProvider()
    cache = UploadCache()
    # Below size_threshold (so it's forced onto the inline path) but above the
    # provider's own inline_size_limit of 100 bytes.
    source = from_bytes(b"x" * 500, mime_type="image/png")

    with pytest.raises(ValueError, match="inline_size_limit"):
        encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert provider.upload_calls == 0


class _ZeroInlineLimitProvider(_RecordingProvider):
    """A provider that returns 0 from inline_size_limit() as the documented
    sentinel for "no fixed inline convention declared" (e.g. GenericHTTPUploadProvider
    for an arbitrary custom endpoint). 0 must NOT be treated as "zero bytes
    allowed" -- small sources should still inline successfully without raising."""

    def inline_size_limit(self) -> int:
        return 0


def test_inline_path_with_zero_inline_size_limit_is_treated_as_no_limit():
    provider = _ZeroInlineLimitProvider()
    cache = UploadCache()
    # Below size_threshold, so it's routed onto the inline path. Previously this
    # raised ValueError because 0 was compared literally instead of being treated
    # as "no declared limit".
    source = from_bytes(b"tiny", mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


async def test_async_inline_path_with_zero_inline_size_limit_is_treated_as_no_limit():
    class _AsyncZeroInlineLimitProvider(_AsyncRecordingProvider):
        def inline_size_limit(self) -> int:
            return 0

    provider = _AsyncZeroInlineLimitProvider()
    cache = UploadCache()
    source = from_bytes(b"tiny", mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


async def test_async_inline_path_raises_when_source_exceeds_providers_inline_size_limit():
    class _AsyncTinyInlineLimitProvider(_AsyncRecordingProvider):
        def inline_size_limit(self) -> int:
            return 100

    provider = _AsyncTinyInlineLimitProvider()
    cache = UploadCache()
    source = from_bytes(b"x" * 500, mime_type="image/png")

    with pytest.raises(ValueError, match="inline_size_limit"):
        await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert provider.upload_calls == 0


class _TinyInlineLimitAlwaysFailsUploadProvider(_RecordingProvider):
    """A provider whose upload always fails AND whose inline_size_limit is tiny --
    proves the fallback-to-inline-on-upload-failure path also respects
    inline_size_limit, not just the size-threshold-triggered inline path."""

    def __init__(self):
        super().__init__(raise_on_upload=True)

    def inline_size_limit(self) -> int:
        return 100


def test_upload_failure_fallback_raises_when_source_exceeds_inline_size_limit():
    provider = _TinyInlineLimitAlwaysFailsUploadProvider()
    cache = UploadCache()
    # Above size_threshold (forces the "try native upload" branch); upload fails
    # and would normally fall back to inline -- but the source also exceeds
    # inline_size_limit, so it must raise instead of silently sending an
    # oversized inline payload.
    source = from_bytes(b"x" * 500, mime_type="image/png")

    with pytest.raises(ValueError, match="inline_size_limit"):
        encode_media_sync(provider, "fake", source, cache, size_threshold=100)

    assert provider.upload_calls == 1


def test_non_seekable_unsupported_media_type_raises_value_error():
    provider = _RecordingProvider(supports=False)
    cache = UploadCache()
    content = b"v" * 5000
    chunks = [content[i : i + 100] for i in range(0, len(content), 100)]
    source = from_iterator(iter(chunks), mime_type="application/weird")

    with pytest.raises(ValueError):
        encode_media_sync(provider, "fake", source, cache, size_threshold=1000)


# Async tests
class _AsyncRecordingProvider(_RecordingProvider):
    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        self.upload_calls += 1
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])
        else:
            data = b"".join(chunks)
        self.uploaded_bytes += data
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        return ProviderRef(id=f"ref-{self.upload_calls}", expires_at=None)


async def test_async_large_seekable_source_uploads_and_caches():
    provider = _AsyncRecordingProvider()
    cache = UploadCache()
    content = b"x" * 2000
    source = from_bytes(content, mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.upload_calls == 1


async def test_async_small_source_goes_inline():
    provider = _AsyncRecordingProvider()
    cache = UploadCache()
    source = from_bytes(b"tiny", mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


async def test_async_upload_failure_falls_back_to_inline():
    provider = _AsyncRecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"


async def test_async_upload_failure_fallback_raises_when_source_exceeds_inline_size_limit():
    class _AsyncTinyInlineLimitAlwaysFailsUploadProvider(_AsyncRecordingProvider):
        def __init__(self):
            super().__init__(raise_on_upload=True)

        def inline_size_limit(self) -> int:
            return 100

    provider = _AsyncTinyInlineLimitAlwaysFailsUploadProvider()
    cache = UploadCache()
    source = from_bytes(b"x" * 500, mime_type="image/png")

    with pytest.raises(ValueError, match="inline_size_limit"):
        await encode_media_async(provider, "fake", source, cache, size_threshold=100)

    assert provider.upload_calls == 1
