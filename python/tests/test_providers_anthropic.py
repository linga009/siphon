from unittest.mock import AsyncMock, MagicMock

from siphon.providers import ProviderRef
from siphon.providers.anthropic_provider import AnthropicProvider


def _fake_file_object(file_id="file_011abc"):
    obj = MagicMock()
    obj.id = file_id
    return obj


def test_supports_media_type_accepts_images_and_pdfs():
    provider = AnthropicProvider(client=MagicMock())
    assert provider.supports_media_type("image/jpeg") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("video/mp4") is False


def test_upload_calls_beta_files_upload_with_beta_header():
    client = MagicMock()
    client.beta.files.upload.return_value = _fake_file_object("file_011xyz")
    provider = AnthropicProvider(client=client)

    ref = provider.upload(iter([b"abc"]), "image/png")

    assert ref.id == "file_011xyz"
    client.beta.files.upload.assert_called_once()
    _, kwargs = client.beta.files.upload.call_args
    assert kwargs["betas"] == ["files-api-2025-04-14"]


async def test_upload_async_calls_beta_files_upload():
    client = MagicMock()
    client.beta.files.upload = AsyncMock(return_value=_fake_file_object("file_011async"))
    provider = AnthropicProvider(client=client)

    ref = await provider.upload_async(iter([b"abc"]), "image/png")

    assert ref.id == "file_011async"
    client.beta.files.upload.assert_awaited_once()


def test_build_reference_block_for_image():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_reference_block(ProviderRef(id="file_1", expires_at=None), "image/png")
    assert block == {"type": "image", "source": {"type": "file", "file_id": "file_1"}}


def test_build_reference_block_for_pdf():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_reference_block(
        ProviderRef(id="file_2", expires_at=None), "application/pdf"
    )
    assert block == {"type": "document", "source": {"type": "file", "file_id": "file_2"}}


def test_build_inline_block_for_image():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_inline_block("AAAA", "image/png")
    assert block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    }
