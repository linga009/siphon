import { describe, expect, it, vi } from "vitest";
import { encodeMedia } from "../src/api.js";
import { registerProvider } from "../src/providers/types.js";
import * as siphon from "../src/index.js";

describe("encodeMedia", () => {
  it("accepts a raw Buffer source and inline-encodes a small payload", async () => {
    registerProvider("stub", {
      supportsMediaType: () => true,
      inlineSizeLimit: () => 10_000_000,
      async upload(): Promise<never> {
        throw new Error("should not upload");
      },
      buildReferenceBlock: () => ({ type: "ref" }),
      buildInlineBlock: (data) => ({ type: "inline", data }),
    });

    const block = await encodeMedia(null, "stub", Buffer.from("tiny"), {
      mimeType: "text/plain",
    });

    expect(block.type).toBe("inline");
  });

  it("throws a clear error for an unregistered provider", async () => {
    await expect(
      encodeMedia(null, "totally-unknown-provider-xyz", Buffer.from("x"), {
        mimeType: "text/plain",
      })
    ).rejects.toThrow(/unknown-provider/);
  });

  it("builds an OpenAIProvider when providerName is openai", async () => {
    const client = {
      files: { create: vi.fn().mockResolvedValue({ id: "file-1" }) },
    } as any;

    const block = await encodeMedia(client, "openai", Buffer.alloc(500_000, "x"), {
      mimeType: "image/png",
      sizeThreshold: 1000,
    });

    expect(block).toEqual({ type: "input_image", file_id: "file-1" });
  });

  it("warns and keeps the original client when a different client is passed for an already-registered builtin provider", async () => {
    // Uses "anthropic" (not "openai", which an earlier test in this file already
    // auto-registers) so this test observes a clean first auto-registration.
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const clientA = {
      beta: { files: { upload: vi.fn().mockResolvedValue({ id: "file-a" }) } },
    } as any;
    const clientB = {
      beta: { files: { upload: vi.fn().mockResolvedValue({ id: "file-b" }) } },
    } as any;

    const blockA = await encodeMedia(clientA, "anthropic", Buffer.alloc(500_000, "x"), {
      mimeType: "image/png",
      sizeThreshold: 1000,
    });
    expect(blockA).toEqual({ type: "image", source: { type: "file", file_id: "file-a" } });
    expect(warnSpy).not.toHaveBeenCalled();

    // Different content than blockA's, so this can't be served from the upload cache and
    // must genuinely go through whichever adapter is bound to the "anthropic" registration.
    const blockB = await encodeMedia(clientB, "anthropic", Buffer.alloc(500_000, "y"), {
      mimeType: "image/png",
      sizeThreshold: 1000,
    });

    // Still served by clientA's adapter, not silently swapped to clientB.
    expect(blockB).toEqual({ type: "image", source: { type: "file", file_id: "file-a" } });
    expect(clientA.beta.files.upload).toHaveBeenCalledTimes(2);
    expect(clientB.beta.files.upload).not.toHaveBeenCalled();
    expect(warnSpy).toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("re-exports the expected public names from index.ts", () => {
    expect(typeof siphon.encodeMedia).toBe("function");
    expect(typeof siphon.registerProvider).toBe("function");
    expect(typeof siphon.fromPath).toBe("function");
    expect(typeof siphon.fromBuffer).toBe("function");
    expect(typeof siphon.fromAsyncIterable).toBe("function");
  });
});
