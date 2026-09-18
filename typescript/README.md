# Siphon (TypeScript)

Stream binary media (images, audio, video, PDFs) to multimodal LLM APIs
without paying Base64's 33% size penalty or buffering whole files in memory.

## Install

    npm install siphon openai @anthropic-ai/sdk @google/genai

Install only the peer packages for the providers you use.

## Usage

    import OpenAI from "openai";
    import { encodeMedia } from "siphon";

    const client = new OpenAI();
    const block = await encodeMedia(client, "openai", "photo.png");

    const response = await client.responses.create({
      model: "gpt-5",
      input: [{ role: "user", content: ["Describe this image.", block] }],
    });

Small files are inlined as Base64 automatically (default threshold: 256 KiB);
larger files are streamed to the provider's native file-upload API and
referenced by ID. Repeated uploads of identical content within the same
process reuse the cached reference instead of re-uploading.

**Not yet live-tested.** Live end-to-end verification against real provider
APIs has so far only been run against the sibling Python package's
`AnthropicProvider` and `GeminiProvider` (see the [root README](../README.md)).
This is a separate implementation of the same design, not a shared core, so
that verification doesn't carry over automatically — treat the TypeScript
adapters as mock-tested only until confirmed live.

## Custom providers

    import { registerProvider, encodeMedia, GenericHTTPUploadProvider } from "siphon";

    registerProvider("my-server", new GenericHTTPUploadProvider("https://my-server/upload"));
    const block = await encodeMedia(null, "my-server", "clip.mp4");

## Groq

Groq has no native file-upload API for vision — images go inline as base64,
in the same JSON shape OpenAI's older Chat Completions API uses. Because its
capability profile differs from the three built-ins (inline-only, images
only), `GroqProvider` isn't auto-registered — register it explicitly:

    import Groq from "groq-sdk";
    import { encodeMedia, registerProvider, GroqProvider } from "siphon";

    const client = new Groq();
    registerProvider("groq", new GroqProvider(client));
    const block = await encodeMedia(client, "groq", "photo.png");

    const response = await client.chat.completions.create({
      model: "meta-llama/llama-4-scout-17b-16e-instruct",
      messages: [{ role: "user", content: ["Describe this image.", block] }],
    });

The request shape was checked against the real Groq API (a well-formed
request was accepted and rejected only for model capability, not malformed
structure) — but not yet a full vision round-trip.

## Known limitations (v1)

- The OpenAI, Anthropic, and Gemini adapters currently buffer the full
  payload into one `Buffer` before handing it to the SDK's upload call
  (their upload helpers expect a complete buffer/Blob, not an arbitrary
  async generator). True zero-buffering native upload is fully implemented
  for the **inline-fallback path** (streaming Base64) and for **custom
  providers** via `GenericHTTPUploadProvider`, which streams a real
  `ReadableStream` body over `fetch`.
- The upload cache is in-memory and per-process; it does not persist across
  restarts and is not shared across multiple processes.
- This package targets Node.js. Browser support (using `File`/`Blob`
  sources instead of `fs`-backed paths) would reuse the same `Provider`
  interface but needs its own `MediaSource` constructors — not built here.
- Node 18 lacks a global `File` constructor (added as a true global in
  Node 20); `OpenAIProvider` polyfills it from `node:buffer` internally
  when absent, so Node 18 still works, but it's worth knowing about if
  you see `File`-related errors from other code sharing the process.

## License

[PolyForm Shield License 1.0.0](LICENSE.md) — free for any use except
providing a competing product or service.
