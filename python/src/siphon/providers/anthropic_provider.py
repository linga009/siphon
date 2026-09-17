"""Anthropic provider adapter: beta Files API + Messages API content blocks."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 5 * 1024 * 1024  # Anthropic's documented base64 image limit
_BETA_HEADER = ["files-api-2025-04-14"]


class AnthropicProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        data = b"".join(chunks)
        file_obj = self._client.beta.files.upload(
            file=("upload", data, mime_type),
            betas=_BETA_HEADER,
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])  # type: ignore[union-attr]
        else:
            data = b"".join(chunks)  # type: ignore[arg-type]
        file_obj = await self._client.beta.files.upload(
            file=("upload", data, mime_type),
            betas=_BETA_HEADER,
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        block_type = "image" if mime_type.startswith("image/") else "document"
        return {"type": block_type, "source": {"type": "file", "file_id": ref.id}}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        block_type = "image" if mime_type.startswith("image/") else "document"
        return {
            "type": block_type,
            "source": {"type": "base64", "media_type": mime_type, "data": base64_data},
        }
