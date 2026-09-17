from unittest.mock import AsyncMock, MagicMock

from siphon.providers import ProviderRef
from siphon.providers.gemini_provider import GeminiProvider


def _fake_file_object(uri="https://generativelanguage.googleapis.com/v1/files/abc123"):
    obj = MagicMock()
    obj.uri = uri
    return obj


def test_supports_media_type_accepts_images_audio_video_pdf():
    provider = GeminiProvider(client=MagicMock())
    assert provider.supports_media_type("image/png") is True
    assert provider.supports_media_type("audio/mp3") is True
    assert provider.supports_media_type("video/mp4") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("application/zip") is False


def test_upload_calls_files_upload_and_returns_ref_with_uri_as_id():
    client = MagicMock()
    client.files.upload.return_value = _fake_file_object("https://example/files/xyz")
    provider = GeminiProvider(client=client)

    ref = provider.upload(iter([b"abc"]), "image/png")

    assert ref.id == "https://example/files/xyz"
    client.files.upload.assert_called_once()


async def test_upload_async_calls_aio_files_upload():
    client = MagicMock()
    client.aio.files.upload = AsyncMock(return_value=_fake_file_object("https://example/files/async1"))
    provider = GeminiProvider(client=client)

    ref = await provider.upload_async(iter([b"abc"]), "image/png")

    assert ref.id == "https://example/files/async1"
    client.aio.files.upload.assert_awaited_once()


def test_build_reference_block_uses_file_data_with_uri():
    provider = GeminiProvider(client=MagicMock())
    block = provider.build_reference_block(
        ProviderRef(id="https://example/files/1", expires_at=None), "image/png"
    )
    assert block == {
        "file_data": {"mime_type": "image/png", "file_uri": "https://example/files/1"}
    }


def test_build_inline_block_uses_inline_data():
    provider = GeminiProvider(client=MagicMock())
    block = provider.build_inline_block("AAAA", "image/png")
    assert block == {"inline_data": {"mime_type": "image/png", "data": "AAAA"}}
