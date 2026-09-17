import httpx
import pytest

from siphon.providers import ProviderRef
from siphon.providers.custom import GenericHTTPUploadProvider, multipart_chunks


def test_multipart_chunks_produces_well_formed_body():
    chunks = multipart_chunks(
        field_name="file",
        filename="photo.png",
        mime_type="image/png",
        chunks=iter([b"AB", b"CD"]),
        boundary="TESTBOUNDARY",
    )
    body = b"".join(chunks)

    assert body.startswith(b"--TESTBOUNDARY\r\n")
    assert b'Content-Disposition: form-data; name="file"; filename="photo.png"' in body
    assert b"Content-Type: image/png" in body
    assert b"ABCD" in body
    assert body.endswith(b"--TESTBOUNDARY--\r\n")


def test_multipart_chunks_rejects_field_name_with_crlf():
    with pytest.raises(ValueError, match="field_name"):
        list(
            multipart_chunks(
                field_name="file\r\nX-Injected: evil",
                filename="photo.png",
                mime_type="image/png",
                chunks=iter([b"AB"]),
                boundary="TESTBOUNDARY",
            )
        )


def test_multipart_chunks_rejects_mime_type_with_newline():
    with pytest.raises(ValueError, match="mime_type"):
        list(
            multipart_chunks(
                field_name="file",
                filename="photo.png",
                mime_type="image/png\nX-Injected: evil",
                chunks=iter([b"AB"]),
                boundary="TESTBOUNDARY",
            )
        )


def test_generic_http_upload_provider_posts_and_parses_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert b"ABCD" in request.read()
        return httpx.Response(200, json={"id": "custom-ref-1", "expires_at": 999.0})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    provider = GenericHTTPUploadProvider(
        upload_url="https://example.com/upload", http_client=http_client
    )

    ref = provider.upload(iter([b"AB", b"CD"]), "image/png")

    assert ref == ProviderRef(id="custom-ref-1", expires_at=999.0)


def test_generic_http_upload_provider_supports_any_media_type():
    provider = GenericHTTPUploadProvider(upload_url="https://example.com/upload")
    assert provider.supports_media_type("application/x-whatever") is True


def test_generic_http_upload_provider_build_blocks():
    provider = GenericHTTPUploadProvider(upload_url="https://example.com/upload")

    ref_block = provider.build_reference_block(ProviderRef(id="r1", expires_at=None), "image/png")
    inline_block = provider.build_inline_block("AAAA", "image/png")

    assert ref_block == {"type": "file_reference", "id": "r1"}
    assert inline_block == {"type": "inline_base64", "mime_type": "image/png", "data": "AAAA"}
