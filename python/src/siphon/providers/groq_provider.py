"""Groq provider adapter: inline-only.

Groq has no native file-upload API for vision -- images are sent inline as
base64 in the Chat Completions request, the same shape OpenAI's older
Chat Completions API uses. There is no upload/reference-by-id path, so
upload() and upload_async() always fail; the orchestrator's documented
upload-failure fallback then routes the request onto the inline path,
where inline_size_limit() still guards against oversized payloads.
"""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/",)

# Groq's vision endpoints accept base64-encoded images up to 4 MiB (the
# encoded payload size). Base64 expands raw bytes by ~4/3, so the raw-byte
# ceiling that keeps the encoded result under 4 MiB is 4 MiB * 3/4 = 3 MiB.
# Source: https://console.groq.com/docs/vision (checked 2026-09-17) -- verify
# against current Groq docs if uploads start failing near this size.
_INLINE_SIZE_LIMIT = 3 * 1024 * 1024

_NO_UPLOAD_MESSAGE = (
    "Groq has no native file-upload API for vision -- images can only be sent "
    "inline as base64. This call should have gone through the inline path; if "
    "you're seeing this error, the image likely exceeds inline_size_limit() "
    f"({_INLINE_SIZE_LIMIT} bytes) with no native-upload alternative to fall "
    "back to."
)


class GroqProvider:
    """Register explicitly (`register_provider("groq", GroqProvider(client))`) --
    unlike OpenAI/Anthropic/Gemini, Groq is not auto-registered by encode_media,
    since its capability profile (inline-only, images only) differs enough from
    the three built-ins that opt-in registration is less surprising."""

    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        raise NotImplementedError(_NO_UPLOAD_MESSAGE)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        raise NotImplementedError(_NO_UPLOAD_MESSAGE)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        raise NotImplementedError(_NO_UPLOAD_MESSAGE)

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{base64_data}"},
        }
