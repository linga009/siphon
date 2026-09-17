"""Gemini provider adapter: Files API (resumable upload) + generateContent blocks."""

from __future__ import annotations

import io
from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "audio/", "video/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 20 * 1024 * 1024  # Gemini's documented inline request-size guidance


class GeminiProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        buffer = io.BytesIO(b"".join(chunks))
        file_obj = self._client.files.upload(
            file=buffer,
            config={"mime_type": mime_type},
        )
        return ProviderRef(id=file_obj.uri, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])  # type: ignore[union-attr]
        else:
            data = b"".join(chunks)  # type: ignore[arg-type]
        buffer = io.BytesIO(data)
        file_obj = await self._client.aio.files.upload(
            file=buffer,
            config={"mime_type": mime_type},
        )
        return ProviderRef(id=file_obj.uri, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"file_data": {"mime_type": mime_type, "file_uri": ref.id}}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
