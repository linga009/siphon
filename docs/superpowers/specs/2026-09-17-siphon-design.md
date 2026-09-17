# Siphon — Design Spec (Stage 1: Smart Multimodal Client Library)

## Problem

Sending binary media (images, audio, video, PDFs) to multimodal LLM APIs today
almost always means Base64-encoding the file into a JSON string. This costs:

- **~33% size overhead** from the encoding itself.
- **Full in-memory buffering** — the file must be fully read and converted to
  a string before any bytes reach the network.
- **No resumability** — if the request fails partway through a large payload,
  the whole thing is resent from scratch.

All three major hosted multimodal APIs (OpenAI, Anthropic, Gemini) now offer
native "upload once, reference by ID" file APIs as an alternative to inline
Base64, but:

- Each provider's upload mechanism is shaped differently (see below).
- None of them make Base64 disappear entirely — small payloads, providers
  without a file API, or endpoints that don't accept `file_id` references
  still need it.
- No existing library unifies "pick the cheapest path per provider, stream
  the bytes, cache the result" behind one call.

Siphon is that unifying layer.

## Scope

This spec covers **Stage 1 only**: a client-side library that works against
today's real hosted multimodal APIs (OpenAI, Anthropic, Gemini) plus a
pluggable extension point for custom/self-hosted providers (e.g. a vLLM
OpenAI-compatible endpoint).

### Non-goals (deferred to a later Stage 2 spec)

- No new wire protocol or binary framing format — that only makes sense once
  a server is under our control (self-hosted inference, or a gateway we own
  in front of a hosted API). Stage 2 will design that, informed by what we
  learn building Stage 1.
- No image/video/audio re-encoding, resizing, downsampling, or transcoding.
  Siphon transports bytes; it does not transform media.
- No persistent (cross-process/cross-restart) upload cache. Provider-side
  file TTLs (hours to days, provider-dependent) make a durable cache a
  correctness hazard — a cached `file_id` could point at an
  already-expired remote file. V1's cache is in-memory and scoped to a
  single client instance's lifetime.

## Provider landscape (verified 2026-09-17)

| Provider | Native upload mechanism | How it's referenced |
|---|---|---|
| **OpenAI** | Files API (`client.files.create`). **Only the Responses API accepts `file_id`** — Chat Completions dropped file-input support in September 2025. | `{"type": "input_file", "file_id": "file-..."}` in a Responses API call |
| **Anthropic** | Files API (beta; requires the `files-api-2025-04-14` beta header) | `{"type": "image", "source": {"type": "file", "file_id": "file-..."}}` |
| **Gemini** | Files API, resumable-upload protocol (`X-Goog-Upload-*` headers); recommended for reused files or anything over 100MB | `{"fileData": {"file_uri": "..."}}` in `generateContent` |

All three official SDKs accept a file path or file-like object for uploads
and stream it at the HTTP layer — they do not require the caller to buffer
the whole file first. Siphon's adapters lean on this rather than
reimplementing multipart/resumable transport for providers that already have
an SDK.

## Architecture

Provider-strategy pattern, three layers:

```
caller
  │
  ▼
encode_media(client, provider, source)     ← public entry point
  │
  ▼
Orchestrator
  1. hash source incrementally as read (content-addressed cache key)
  2. cache hit (provider + hash, not expired)?  → return cached ref block
  3. size < threshold?                          → inline-encode (streamed
                                                    base64), return block
  4. else                                        → provider.upload(stream),
                                                    cache the ref, return block
  5. upload failed / unsupported?                → fall back to inline,
                                                    log a warning
  │
  ▼
Provider adapter (OpenAIProvider | AnthropicProvider | GeminiProvider | custom)
  - upload(stream, mime_type) -> ProviderRef
  - build_content_block(ref | inline_payload) -> dict
  - inline_size_limit
  - supports_media_type(mime_type) -> bool
```

Adapters wrap an SDK client instance **supplied by the caller** — Siphon
never manages API keys, auth headers, or retry/backoff itself. This keeps
Siphon compatible with however the caller already configures the official
SDK (org headers, custom base URLs, proxies, retry policy) and avoids
duplicating logic the SDKs already handle well.

### Pluggable custom providers

Same three-method interface. For providers without an official SDK (e.g. a
bare vLLM OpenAI-compatible server with no Files API), Siphon ships one
concrete streaming multipart uploader that a custom adapter can reuse
directly, or a custom adapter can implement its own transport entirely.

### Streaming

- **Native upload path**: the source is opened as a stream (file handle,
  async iterator, or wrapped in-memory buffer) and handed directly to the
  SDK's upload call — no eager full read.
- **Inline fallback path**: Base64 encoding is done in fixed-size chunks
  (a streaming encoder), so even the fallback never buffers the entire file
  just to convert it — memory stays flat regardless of file size.
- Content hashing (for the cache key) happens as a side effect of the same
  streaming read — one pass, not a separate full read to hash plus another
  to upload.

### Caching

- Key: `(provider_name, content_hash)`. Hash algorithm: BLAKE2b (fast,
  no license concerns, streaming-friendly).
- Store: in-memory dict on the orchestrator/client instance. No disk, no
  cross-process sharing.
- Value: provider ref (`file_id`/`file_uri`) plus the provider's own
  reported expiry, when available; entries past expiry are treated as
  misses and re-uploaded.
- Rationale: this is the cheapest correct thing that helps the common case
  (same system image/logo/reference file sent across many calls in one
  process) without taking on the risk of stale cross-run state.

### Decision threshold

- Default inline-vs-upload cutoff: **256 KB**, configurable per call and
  per client. Below it, the round-trip cost of a separate upload call isn't
  worth it; above it, native upload wins on both bandwidth and memory.
- If a provider/media-type combination has no native upload path at all
  (e.g. a media type the provider's Files API doesn't accept), Siphon
  always falls back to inline regardless of size, and surfaces a warning so
  callers aren't silently paying the Base64 cost without knowing why.

## Public API

Conceptually identical across languages: give it a configured provider
client, a provider name, and a source; get back a ready-to-splice content
block. Python and TypeScript are independent implementations sharing this
contract, not a shared compiled core.

### Python (sync + async)

```python
from siphon import encode_media, encode_media_async

block = encode_media(openai_client, "openai", "photo.png")
# -> {"type": "input_file", "file_id": "file-abc"}  (or inline dict)

block = await encode_media_async(openai_client, "openai", "photo.png")
```

Custom provider registration:

```python
from siphon import register_provider

register_provider("my-vllm", MyVLLMProvider(base_url=..., streaming_uploader=...))
```

### TypeScript

```typescript
import { encodeMedia, registerProvider } from "siphon";

const block = await encodeMedia(openaiClient, "openai", filePathOrStream);
```

## Error handling

- Upload failures (network error, auth error, unsupported type) trigger the
  inline-fallback path described above, unless the caller has explicitly
  disabled fallback for that call (`allow_inline_fallback=False`), in which
  case the original error propagates.
- Siphon does not add its own retry loop around provider uploads — retries
  are the SDK's responsibility, per the "don't duplicate what the SDK
  already does" principle above.
- All fallback-triggering events are logged at `WARNING` via the standard
  `logging`/equivalent facility, including the reason (size threshold vs.
  unsupported vs. upload error), so silent cost regressions are visible.

## Testing

- **Unit tests**: mock the provider SDKs' HTTP layer (`respx` for Python's
  `httpx`-based SDKs; `msw` for the TypeScript SDKs). No real network calls,
  no cost, run in every CI job.
- **Integration tests**: a separate, opt-in suite gated behind environment
  variables holding real API keys. Exercises the three real providers
  end-to-end (small-file inline path, large-file native-upload path, cache
  hit path). Run manually or on a scheduled job — not on every commit.

## Package

- Name: **Siphon** (`siphon` on PyPI, `siphon` on npm — availability to be
  confirmed at implementation time; fall back to a scoped/suffixed name if
  taken).
- Two independent packages/repos-or-directories: `python/` and `typescript/`
  (or `packages/siphon-py`, `packages/siphon-js` if kept in one repo —
  decided at planning time).
