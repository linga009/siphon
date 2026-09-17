"""OpenAI provider adapter: Files API + Responses API content blocks."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 20 * 1024 * 1024  # OpenAI's documented data-URL image limit


class _ChunkFile:
    """Wraps a byte-chunk iterator so it looks enough like a file for the SDK."""

    def __init__(self, chunks: Iterator[bytes], name: str) -> None:
        self._chunks = chunks
        self.name = name

    def read(self, *_args) -> bytes:
        return b"".join(self._chunks)


class OpenAIProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        file_obj = self._client.files.create(
            file=_ChunkFile(chunks, name="upload"),
            purpose="user_data",
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            collected = [c async for c in chunks]  # type: ignore[union-attr]
        else:
            collected = list(chunks)  # type: ignore[arg-type]
        file_obj = await self._client.files.create(
            file=_ChunkFile(iter(collected), name="upload"),
            purpose="user_data",
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        block_type = "input_image" if mime_type.startswith("image/") else "input_file"
        return {"type": block_type, "file_id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        data_url = f"data:{mime_type};base64,{base64_data}"
        if mime_type.startswith("image/"):
            return {"type": "input_image", "image_url": data_url}
        return {"type": "input_file", "file_data": data_url, "filename": "upload"}
