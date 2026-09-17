import { describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "../../src/providers/anthropicProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(fileId: string) {
  return {
    beta: {
      files: {
        upload: vi.fn().mockResolvedValue({ id: fileId }),
      },
    },
  } as any;
}

describe("AnthropicProvider", () => {
  it("supports images and PDFs but not video", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/jpeg")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("video/mp4")).toBe(false);
  });

  it("uploads via beta.files.upload with the files-api beta header", async () => {
    const client = makeFakeClient("file_011xyz");
    const provider = new AnthropicProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("abc")]), "image/png");

    expect(ref).toEqual({ id: "file_011xyz", expiresAt: null });
    expect(client.beta.files.upload).toHaveBeenCalledTimes(1);
    const params = client.beta.files.upload.mock.calls[0][0];
    expect(params.betas).toEqual(["files-api-2025-04-14"]);
  });

  it("builds an image reference block", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.buildReferenceBlock({ id: "file_1", expiresAt: null }, "image/png")).toEqual({
      type: "image",
      source: { type: "file", file_id: "file_1" },
    });
  });

  it("builds a document reference block for PDFs", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "file_2", expiresAt: null }, "application/pdf")
    ).toEqual({ type: "document", source: { type: "file", file_id: "file_2" } });
  });

  it("builds an inline base64 image block", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "image",
      source: { type: "base64", media_type: "image/png", data: "AAAA" },
    });
  });
});
