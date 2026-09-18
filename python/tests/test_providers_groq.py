import pytest

from siphon.providers.groq_provider import GroqProvider


def test_supports_media_type_accepts_only_images():
    provider = GroqProvider(client=None)
    assert provider.supports_media_type("image/png") is True
    assert provider.supports_media_type("image/jpeg") is True
    assert provider.supports_media_type("application/pdf") is False
    assert provider.supports_media_type("audio/mpeg") is False
    assert provider.supports_media_type("video/mp4") is False


def test_inline_size_limit_is_positive_and_leaves_room_for_base64_expansion():
    provider = GroqProvider(client=None)
    limit = provider.inline_size_limit()

    assert limit > 0
    # Groq's documented base64 payload cap is 4 MiB; the raw-byte limit must
    # leave room for base64's ~4/3 expansion so the encoded result still fits.
    assert limit * 4 / 3 <= 4 * 1024 * 1024


def test_upload_raises_not_implemented_error():
    provider = GroqProvider(client=None)

    with pytest.raises(NotImplementedError, match="no native file-upload API"):
        provider.upload(iter([b"data"]), "image/png")


async def test_upload_async_raises_not_implemented_error():
    provider = GroqProvider(client=None)

    with pytest.raises(NotImplementedError, match="no native file-upload API"):
        await provider.upload_async(iter([b"data"]), "image/png")


def test_build_reference_block_raises_not_implemented_error():
    from siphon.providers import ProviderRef

    provider = GroqProvider(client=None)

    with pytest.raises(NotImplementedError, match="no native file-upload API"):
        provider.build_reference_block(ProviderRef(id="x", expires_at=None), "image/png")


def test_build_inline_block_produces_chat_completions_image_url_shape():
    provider = GroqProvider(client=None)

    block = provider.build_inline_block("AAAA", "image/png")

    assert block == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,AAAA"},
    }
