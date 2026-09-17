import { describe, expect, it, vi } from "vitest";
import { UploadCache } from "../src/cache.js";
import { hashChunks } from "../src/hashing.js";
import { encodeMediaCore } from "../src/orchestrator.js";
import type { Provider, ProviderRef } from "../src/providers/types.js";
import { fromAsyncIterable, fromBuffer } from "../src/sources.js";

class RecordingProvider implements Provider {
  uploadCalls = 0;
  uploadedBytes = Buffer.alloc(0);

  constructor(
    private supports = true,
    private raiseOnUpload = false,
    private inlineLimit = 10_000_000
  ) {}

  supportsMediaType(): boolean {
    return this.supports;
  }

  inlineSizeLimit(): number {
    return this.inlineLimit;
  }

  async upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef> {
    this.uploadCalls += 1;
    const parts: Buffer[] = [];
    for await (const chunk of chunks) parts.push(chunk);
    this.uploadedBytes = Buffer.concat([this.uploadedBytes, ...parts]);
    if (this.raiseOnUpload) throw new Error("upload failed");
    return { id: `ref-${this.uploadCalls}`, expiresAt: null };
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    return { type: "ref", id: ref.id };
  }

  buildInlineBlock(data: string, mimeType: string): Record<string, unknown> {
    return { type: "inline", data };
  }
}

describe("encodeMediaCore", () => {
  it("goes inline for a small seekable source without calling upload", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.from("tiny"), "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(provider.uploadCalls).toBe(0);
  });

  it("uploads and caches a large seekable source", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(2000, "x");
    const source = fromBuffer(content, "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block).toEqual({ type: "ref", id: "ref-1" });
    expect(provider.uploadCalls).toBe(1);
    expect(provider.uploadedBytes).toEqual(content);
  });

  it("hits the cache on a second call with identical content and does not re-upload", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(2000, "y");

    const block1 = await encodeMediaCore(
      provider,
      "fake",
      fromBuffer(content, "image/png"),
      cache,
      1000
    );
    const block2 = await encodeMediaCore(
      provider,
      "fake",
      fromBuffer(content, "image/png"),
      cache,
      1000
    );

    expect(block1).toEqual(block2);
    expect(provider.uploadCalls).toBe(1);
  });

  it("throws when the size-threshold-triggered inline path would exceed the provider's inline size limit", async () => {
    // supports the media type (so the size-threshold branch, not the unsupported-type
    // branch, is what decides to go inline) but declares a tiny inline size limit.
    const provider = new RecordingProvider(true, false, 100);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(500, "x"), "image/png");

    // sizeThreshold is larger than the content, so this is forced onto the inline path.
    await expect(encodeMediaCore(provider, "fake", source, cache, 1000)).rejects.toThrow(
      /inline size limit/
    );
    expect(provider.uploadCalls).toBe(0);
  });

  it("goes inline for an unsupported media type even if large", async () => {
    const provider = new RecordingProvider(false);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "application/weird");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(provider.uploadCalls).toBe(0);
  });

  it("falls back to inline when upload fails and fallback is allowed", async () => {
    const provider = new RecordingProvider(true, true);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "image/png");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("re-throws when upload fails and fallback is disabled", async () => {
    const provider = new RecordingProvider(true, true);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "image/png");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(encodeMediaCore(provider, "fake", source, cache, 1000, false)).rejects.toThrow(
      "upload failed"
    );
    expect(warnSpy).not.toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("re-throws when a non-seekable source upload fails, even with fallback allowed", async () => {
    const provider = new RecordingProvider(true, true);
    const cache = new UploadCache();
    const content = Buffer.alloc(5000, "z");
    async function* gen() {
      for (let i = 0; i < content.length; i += 100) yield content.subarray(i, i + 100);
    }
    const source = fromAsyncIterable(gen(), "image/png");

    await expect(
      encodeMediaCore(provider, "fake", source, cache, 1000, true)
    ).rejects.toThrow("upload failed");
  });

  it("uploads a non-seekable source and populates the cache after success", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(5000, "z");
    async function* gen() {
      for (let i = 0; i < content.length; i += 100) yield content.subarray(i, i + 100);
    }
    const source = fromAsyncIterable(gen(), "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block).toEqual({ type: "ref", id: "ref-1" });
    expect(provider.uploadedBytes).toEqual(content);

    const expectedHash = await hashChunks(
      (async function* () {
        for (let i = 0; i < content.length; i += 100) yield content.subarray(i, i + 100);
      })()
    );
    expect(cache.get("fake", expectedHash)).not.toBeNull();
  });
});
