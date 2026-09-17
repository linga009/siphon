import logging

import pytest

from siphon.cache import UploadCache
from siphon.orchestrator import encode_media_sync
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
    assert any("upload failed" in record.message.lower() or "fall" in record.message.lower()
               for record in caplog.records)


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
    source = from_iterator(iter([content[i : i + 100] for i in range(0, len(content), 100)]),
                            mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.uploaded_bytes == content
