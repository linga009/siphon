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

## Custom providers

    from siphon import register_provider
    from siphon.providers.custom import GenericHTTPUploadProvider

    register_provider("my-server", GenericHTTPUploadProvider("https://my-server/upload"))
    block = encode_media(None, "my-server", "clip.mp4")

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
