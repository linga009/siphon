import { describe, expect, it, vi } from "vitest";
import { GenericHTTPUploadProvider, multipartChunks } from "../../src/providers/custom.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

async function collect(it: AsyncIterable<Buffer>): Promise<Buffer> {
  const parts: Buffer[] = [];
  for await (const chunk of it) parts.push(chunk);
  return Buffer.concat(parts);
}

describe("multipartChunks", () => {
  it("produces a well-formed multipart body", async () => {
    const body = await collect(
      multipartChunks(
        "file",
        "photo.png",
        "image/png",
        toAsyncIterable([Buffer.from("AB"), Buffer.from("CD")]),
        "TESTBOUNDARY"
      )
    );

    expect(body.toString("latin1")).toContain("--TESTBOUNDARY\r\n");
    expect(body.toString("latin1")).toContain(
      'Content-Disposition: form-data; name="file"; filename="photo.png"'
    );
    expect(body.toString("latin1")).toContain("Content-Type: image/png");
    expect(body.toString("latin1")).toContain("ABCD");
    expect(body.toString("latin1")).toMatch(/--TESTBOUNDARY--\r\n$/);
  });
});

describe("GenericHTTPUploadProvider", () => {
  it("supports any media type", () => {
    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    expect(provider.supportsMediaType("application/x-whatever")).toBe(true);
  });

  it("posts the stream and parses the returned id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "custom-ref-1", expiresAt: 999 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    const ref = await provider.upload(toAsyncIterable([Buffer.from("AB")]), "image/png");

    expect(ref).toEqual({ id: "custom-ref-1", expiresAt: 999 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.com/upload",
      expect.objectContaining({ method: "POST" })
    );

    vi.unstubAllGlobals();
  });

  it("builds generic reference and inline blocks", () => {
    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    expect(provider.buildReferenceBlock({ id: "r1", expiresAt: null }, "image/png")).toEqual({
      type: "file_reference",
      id: "r1",
    });
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "inline_base64",
      mimeType: "image/png",
      data: "AAAA",
    });
  });
});
