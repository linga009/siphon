import type { Provider, ProviderRef } from "./types.js";

const SUPPORTED_PREFIXES = ["image/"];

// Groq's vision endpoints accept base64-encoded images up to 4 MiB (the
// encoded payload size). Base64 expands raw bytes by ~4/3, so the raw-byte
// ceiling that keeps the encoded result under 4 MiB is 4 MiB * 3/4 = 3 MiB.
// Source: https://console.groq.com/docs/vision (checked 2026-09-17) -- verify
// against current Groq docs if uploads start failing near this size.
const INLINE_SIZE_LIMIT = 3 * 1024 * 1024;

const NO_UPLOAD_MESSAGE =
  "Groq has no native file-upload API for vision -- images can only be sent " +
  "inline as base64. This call should have gone through the inline path; if " +
  "you're seeing this error, the image likely exceeds inlineSizeLimit() " +
  `(${INLINE_SIZE_LIMIT} bytes) with no native-upload alternative to fall back to.`;

/**
 * Register explicitly (`registerProvider("groq", new GroqProvider(client))`) --
 * unlike OpenAI/Anthropic/Gemini, Groq is not auto-registered by encodeMedia,
 * since its capability profile (inline-only, images only) differs enough from
 * the three built-ins that opt-in registration is less surprising.
 */
export class GroqProvider implements Provider {
  constructor(private client: unknown) {}

  supportsMediaType(mimeType: string): boolean {
    return SUPPORTED_PREFIXES.some((prefix) => mimeType.startsWith(prefix));
  }

  inlineSizeLimit(): number {
    return INLINE_SIZE_LIMIT;
  }

  async upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef> {
    throw new Error(NO_UPLOAD_MESSAGE);
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    throw new Error(NO_UPLOAD_MESSAGE);
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    return {
      type: "image_url",
      image_url: { url: `data:${mimeType};base64,${base64Data}` },
    };
  }
}
