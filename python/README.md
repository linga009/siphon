# Siphon (Python)

Stream binary media (images, audio, video, PDFs) to multimodal LLM APIs
without paying Base64's 33% size penalty or buffering whole files in memory.

## Install

    pip install siphon[openai,anthropic,gemini]

Install only the extras for the providers you use.

## Usage

    from openai import OpenAI
    from siphon import encode_media

    client = OpenAI()
    block = encode_media(client, "openai", "photo.png")

    response = client.responses.create(
        model="gpt-5",
        input=[{"role": "user", "content": ["Describe this image.", block]}],
    )

Small files are inlined as Base64 automatically (default threshold: 256 KiB);
larger files are streamed to the provider's native file-upload API and
referenced by ID. Repeated uploads of identical content within the same
process reuse the cached reference instead of re-uploading.

**Live-tested against Anthropic and Gemini.** Both `AnthropicProvider` and
`GeminiProvider` have been verified end-to-end against their real APIs
with `size_threshold=0` (forcing the native-upload path, not the inline
fallback):

- Anthropic: `encode_media(client, "anthropic", image_path, size_threshold=0)`
  streamed a real image to Anthropic's Files API, got back a genuine
  `file_id`, and a follow-up
  `client.beta.messages.create(betas=["files-api-2025-04-14"], ...)` call
  referencing that file returned a correct vision response.
- Gemini: `encode_media(client, "gemini", image_path, size_threshold=0)`
  streamed a real image to Gemini's Files API, got back a genuine
  `file_uri`, and a follow-up `client.models.generate_content(...)` call
  referencing that file returned a correct vision response.

`OpenAIProvider` is covered by mocked unit tests only so far — not yet
verified against the live API.

## Custom providers

    from siphon import register_provider
    from siphon.providers.custom import GenericHTTPUploadProvider

    register_provider("my-server", GenericHTTPUploadProvider("https://my-server/upload"))
    block = encode_media(None, "my-server", "clip.mp4")

## Groq

Groq has no native file-upload API for vision — images go inline as base64,
in the same JSON shape OpenAI's older Chat Completions API uses. Because its
capability profile differs from the three built-ins (inline-only, images
only), `GroqProvider` isn't auto-registered — register it explicitly:

    from groq import Groq
    from siphon import encode_media, register_provider
    from siphon.providers.groq_provider import GroqProvider

    client = Groq()
    register_provider("groq", GroqProvider(client))
    block = encode_media(client, "groq", "photo.png")

    response = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{"role": "user", "content": ["Describe this image.", block]}],
    )

**Not yet fully live-verified.** The request shape was checked against the
real Groq API — a well-formed request was accepted and rejected only for
model capability (no vision model enabled on the test account), not for
malformed structure — but a full vision round-trip (upload → correct
description back) hasn't been confirmed the way Anthropic and Gemini have.

## Known limitations (v1)

- The OpenAI and Anthropic adapters currently buffer the full payload
  in-process before handing it to the SDK's upload call (the official SDKs'
  synchronous file-upload methods expect a seekable file-like object or
  bytes, not an arbitrary chunk iterator). The Gemini adapter does the same.
  True zero-buffering native upload is fully implemented for the
  **inline-fallback path** (streaming Base64) and for **custom providers**
  via `GenericHTTPUploadProvider`. Tightening the built-in three adapters to
  stream to disk-backed temp files (bounding memory to a fixed chunk size
  regardless of payload size) is tracked as follow-up work, not required for
  correctness.
- The upload cache is in-memory and per-process; it does not persist across
  restarts and is not shared across multiple processes.

## License

[PolyForm Shield License 1.0.0](LICENSE.md) — free for any use except
providing a competing product or service.
