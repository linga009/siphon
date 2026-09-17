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

## Custom providers

    import { registerProvider, encodeMedia, GenericHTTPUploadProvider } from "siphon";

    registerProvider("my-server", new GenericHTTPUploadProvider("https://my-server/upload"));
    const block = await encodeMedia(null, "my-server", "clip.mp4");

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
