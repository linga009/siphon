import { describe, expect, it, vi } from "vitest";
import { GeminiProvider } from "../../src/providers/geminiProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(uri: string) {
  return {
    files: {
      upload: vi.fn().mockResolvedValue({ uri }),
    },
  } as any;
}

describe("GeminiProvider", () => {
  it("supports images, audio, video, and PDFs but not arbitrary binaries", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/png")).toBe(true);
    expect(provider.supportsMediaType("audio/mp3")).toBe(true);
    expect(provider.supportsMediaType("video/mp4")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("application/zip")).toBe(false);
  });

  it("uploads via files.upload and uses the returned uri as the ref id", async () => {
    const client = makeFakeClient("https://example/files/xyz");
    const provider = new GeminiProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("abc")]), "image/png");

    expect(ref).toEqual({ id: "https://example/files/xyz", expiresAt: null });
    expect(client.files.upload).toHaveBeenCalledTimes(1);
  });

  it("builds a reference block using file_data with the uri", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "https://example/files/1", expiresAt: null }, "image/png")
    ).toEqual({ file_data: { mime_type: "image/png", file_uri: "https://example/files/1" } });
  });

  it("builds an inline_data block", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      inline_data: { mime_type: "image/png", data: "AAAA" },
    });
  });
});
