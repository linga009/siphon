from unittest.mock import MagicMock

import pytest

import siphon
from siphon import encode_media
from siphon.providers import ProviderRef


def test_encode_media_accepts_raw_bytes_source_and_inline_encodes_small_payload():
    from siphon.providers import register_provider

    class _StubProvider:
        def supports_media_type(self, mime_type): return True
        def inline_size_limit(self): return 10_000_000
        def upload(self, chunks, mime_type): raise AssertionError("should not upload")
        async def upload_async(self, chunks, mime_type): raise AssertionError
        def build_reference_block(self, ref, mime_type): return {"type": "ref"}
        def build_inline_block(self, data, mime_type): return {"type": "inline", "data": data}

    register_provider("stub", _StubProvider())

    block = encode_media(client=None, provider_name="stub", source=b"tiny", mime_type="text/plain")

    assert block["type"] == "inline"


def test_encode_media_raises_clear_error_for_unregistered_provider():
    with pytest.raises(KeyError, match="unknown-provider"):
        encode_media(client=None, provider_name="totally-unknown-provider-xyz", source=b"x", mime_type="text/plain")


def test_encode_media_with_openai_client_builds_openai_provider():
    fake_file = MagicMock()
    fake_file.id = "file-1"
    client = MagicMock()
    client.files.create.return_value = fake_file

    block = encode_media(
        client=client,
        provider_name="openai",
        source=b"x" * 500_000,
        mime_type="image/png",
        size_threshold=1000,
    )

    assert block == {"type": "input_image", "file_id": "file-1"}


def test_siphon_package_exports_expected_names():
    assert hasattr(siphon, "encode_media")
    assert hasattr(siphon, "encode_media_async")
    assert hasattr(siphon, "register_provider")
    assert hasattr(siphon, "from_path")
    assert hasattr(siphon, "from_bytes")
    assert hasattr(siphon, "from_iterator")
