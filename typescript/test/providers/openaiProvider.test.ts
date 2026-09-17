import { describe, expect, it, vi } from "vitest";
import { OpenAIProvider } from "../../src/providers/openaiProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(fileId: string) {
  return {
    files: {
      create: vi.fn().mockResolvedValue({ id: fileId }),
    },
  } as any;
}

describe("OpenAIProvider", () => {
  it("supports images and PDFs but not audio", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/png")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("audio/mpeg")).toBe(false);
  });

  it("uploads via files.create with purpose user_data", async () => {
    const client = makeFakeClient("file-xyz");
    const provider = new OpenAIProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("hello")]), "image/png");

    expect(ref).toEqual({ id: "file-xyz", expiresAt: null });
    expect(client.files.create).toHaveBeenCalledTimes(1);
    const callArgs = client.files.create.mock.calls[0][0];
    expect(callArgs.purpose).toBe("user_data");
  });

  it("builds an input_image reference block for images", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildReferenceBlock({ id: "file-1", expiresAt: null }, "image/png")).toEqual({
      type: "input_image",
      file_id: "file-1",
    });
  });

  it("builds an input_file reference block for PDFs", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "file-2", expiresAt: null }, "application/pdf")
    ).toEqual({ type: "input_file", file_id: "file-2" });
  });

  it("wraps raw base64 in a data URL for inline images", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "input_image",
      image_url: "data:image/png;base64,AAAA",
    });
  });

  it("wraps raw base64 in file_data for inline PDFs", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "application/pdf")).toEqual({
      type: "input_file",
      file_data: "data:application/pdf;base64,AAAA",
      filename: "upload",
    });
  });
});
