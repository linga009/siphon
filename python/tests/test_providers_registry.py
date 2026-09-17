import pytest

from siphon.providers import ProviderRef, get_provider, register_provider


class _FakeProvider:
    def supports_media_type(self, mime_type: str) -> bool:
        return True

    def inline_size_limit(self) -> int:
        return 1024

    def upload(self, chunks, mime_type: str) -> ProviderRef:
        return ProviderRef(id="fake-1", expires_at=None)

    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        return ProviderRef(id="fake-1", expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "fake", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "fake-inline", "data": base64_data}


def test_register_and_get_provider_round_trip():
    provider = _FakeProvider()
    register_provider("fake", provider)

    assert get_provider("fake") is provider


def test_get_unregistered_provider_raises_key_error():
    with pytest.raises(KeyError, match="unknown-provider"):
        get_provider("unknown-provider")


def test_provider_ref_is_a_plain_dataclass():
    ref = ProviderRef(id="abc", expires_at=123.0)
    assert ref.id == "abc"
    assert ref.expires_at == 123.0
