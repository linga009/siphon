"""Generic streaming multipart uploader for custom/self-hosted providers."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

import httpx

from siphon.providers import ProviderRef


def multipart_chunks(
    field_name: str,
    filename: str,
    mime_type: str,
    chunks: Iterator[bytes],
    boundary: str,
) -> Iterator[bytes]:
    preamble = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    yield preamble
    for chunk in chunks:
        yield chunk
    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


class GenericHTTPUploadProvider:
    """A minimal Provider for a self-hosted endpoint that accepts multipart uploads
    and returns JSON with an "id" field. Subclass or wrap this to match a specific
    endpoint's request/response shape.
    """

    def __init__(
        self,
        upload_url: str,
        field_name: str = "file",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._upload_url = upload_url
        self._field_name = field_name
        self._client = http_client or httpx.Client()

    def supports_media_type(self, mime_type: str) -> bool:
        return True

    def inline_size_limit(self) -> int:
        return 0  # no fixed inline convention for an arbitrary custom endpoint

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        boundary = "SiphonBoundary7f3a9c"
        body = multipart_chunks(self._field_name, "upload", mime_type, chunks, boundary)
        response = self._client.post(
            self._upload_url,
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        response.raise_for_status()
        data = response.json()
        return ProviderRef(id=data["id"], expires_at=data.get("expires_at"))

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            collected = [c async for c in chunks]  # type: ignore[union-attr]
        else:
            collected = list(chunks)  # type: ignore[arg-type]
        boundary = "SiphonBoundary7f3a9c"
        body = b"".join(multipart_chunks(self._field_name, "upload", mime_type, iter(collected), boundary))
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._upload_url,
                content=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        response.raise_for_status()
        data = response.json()
        return ProviderRef(id=data["id"], expires_at=data.get("expires_at"))

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "file_reference", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "inline_base64", "mime_type": mime_type, "data": base64_data}
