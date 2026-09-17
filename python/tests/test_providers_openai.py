from unittest.mock import AsyncMock, MagicMock

import pytest

from siphon.providers.openai_provider import OpenAIProvider


def _fake_file_object(file_id="file-abc123"):
    obj = MagicMock()
    obj.id = file_id
    return obj


def test_supports_media_type_accepts_images_and_pdfs():
    provider = OpenAIProvider(client=MagicMock())
    assert provider.supports_media_type("image/png") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("audio/mpeg") is False


def test_upload_calls_files_create_and_returns_ref():
    client = MagicMock()
    client.files.create.return_value = _fake_file_object("file-xyz")
    provider = OpenAIProvider(client=client)

    ref = provider.upload(iter([b"hello", b"world"]), "image/png")

    assert ref.id == "file-xyz"
    assert ref.expires_at is None
    client.files.create.assert_called_once()
    _, kwargs = client.files.create.call_args
    assert kwargs["purpose"] == "user_data"
    # Verify that the _ChunkFile wrapping correctly joins chunks via .read()
    file_obj = kwargs["file"]
    assert file_obj.read() == b"helloworld"


async def test_upload_async_calls_files_create_and_returns_ref():
    client = MagicMock()
    client.files.create = AsyncMock(return_value=_fake_file_object("file-async-1"))
    provider = OpenAIProvider(client=client)

    ref = await provider.upload_async(iter([b"hello"]), "image/png")

    assert ref.id == "file-async-1"
    client.files.create.assert_awaited_once()
    # Verify that the _ChunkFile wrapping correctly joins chunks via .read()
    _, kwargs = client.files.create.call_args
    file_obj = kwargs["file"]
    assert file_obj.read() == b"hello"


def test_build_reference_block_for_image_uses_input_image_type():
    provider = OpenAIProvider(client=MagicMock())
    from siphon.providers import ProviderRef

    block = provider.build_reference_block(ProviderRef(id="file-1", expires_at=None), "image/png")

    assert block == {"type": "input_image", "file_id": "file-1"}


def test_build_reference_block_for_pdf_uses_input_file_type():
    provider = OpenAIProvider(client=MagicMock())
    from siphon.providers import ProviderRef

    block = provider.build_reference_block(
        ProviderRef(id="file-2", expires_at=None), "application/pdf"
    )

    assert block == {"type": "input_file", "file_id": "file-2"}


def test_build_inline_block_for_image_wraps_raw_base64_in_a_data_url():
    provider = OpenAIProvider(client=MagicMock())

    block = provider.build_inline_block("AAAA", "image/png")

    assert block == {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}


def test_build_inline_block_for_pdf_wraps_raw_base64_in_file_data():
    provider = OpenAIProvider(client=MagicMock())

    block = provider.build_inline_block("AAAA", "application/pdf")

    assert block == {
        "type": "input_file",
        "file_data": "data:application/pdf;base64,AAAA",
        "filename": "upload",
    }


def test_inline_size_limit_is_positive():
    provider = OpenAIProvider(client=MagicMock())
    assert provider.inline_size_limit() > 0
