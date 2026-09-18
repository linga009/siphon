import { describe, expect, it } from "vitest";
import { GroqProvider } from "../../src/providers/groqProvider.js";
import type { ProviderRef } from "../../src/providers/types.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

describe("GroqProvider", () => {
  it("supports only images", () => {
    const provider = new GroqProvider(null);
    expect(provider.supportsMediaType("image/png")).toBe(true);
    expect(provider.supportsMediaType("image/jpeg")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(false);
    expect(provider.supportsMediaType("audio/mpeg")).toBe(false);
    expect(provider.supportsMediaType("video/mp4")).toBe(false);
  });

  it("has a positive inline size limit that leaves room for base64 expansion", () => {
    const provider = new GroqProvider(null);
    const limit = provider.inlineSizeLimit();

    expect(limit).toBeGreaterThan(0);
    // Groq's documented base64 payload cap is 4 MiB; the raw-byte limit must
    // leave room for base64's ~4/3 expansion so the encoded result still fits.
    expect((limit * 4) / 3).toBeLessThanOrEqual(4 * 1024 * 1024);
  });

  it("upload() rejects with a clear no-native-upload error", async () => {
    const provider = new GroqProvider(null);

    await expect(provider.upload(toAsyncIterable([Buffer.from("data")]), "image/png")).rejects.toThrow(
      /no native file-upload API/
    );
  });

  it("buildReferenceBlock() throws a clear no-native-upload error", () => {
    const provider = new GroqProvider(null);
    const ref: ProviderRef = { id: "x", expiresAt: null };

    expect(() => provider.buildReferenceBlock(ref, "image/png")).toThrow(/no native file-upload API/);
  });

  it("builds a Chat Completions image_url block for inline data", () => {
    const provider = new GroqProvider(null);

    const block = provider.buildInlineBlock("AAAA", "image/png");

    expect(block).toEqual({
      type: "image_url",
      image_url: { url: "data:image/png;base64,AAAA" },
    });
  });
});
