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
    let capturedBody: unknown;
    const fetchMock = vi.fn().mockImplementation(async (_url: string, init: RequestInit) => {
      capturedBody = init.body;
      return {
        ok: true,
        json: async () => ({ id: "custom-ref-1", expires_at: 999 }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    const ref = await provider.upload(toAsyncIterable([Buffer.from("AB"), Buffer.from("CD")]), "image/png");

    expect(ref).toEqual({ id: "custom-ref-1", expiresAt: 999 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.com/upload",
      expect.objectContaining({ method: "POST" })
    );

    // Actually drain the ReadableStream passed as `body` to prove upload() wires the
    // streaming multipart bytes through end-to-end, not just that fetch was invoked.
    expect(capturedBody).toBeInstanceOf(ReadableStream);
    const reader = (capturedBody as ReadableStream<Uint8Array>).getReader();
    const received: Buffer[] = [];
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      received.push(Buffer.from(value));
    }
    const bodyBytes = Buffer.concat(received).toString("latin1");

    expect(bodyBytes).toBe(
      `--SiphonBoundary7f3a9c\r\n` +
        `Content-Disposition: form-data; name="file"; filename="upload"\r\n` +
        `Content-Type: image/png\r\n\r\n` +
        `ABCD` +
        `\r\n--SiphonBoundary7f3a9c--\r\n`
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
      mime_type: "image/png",
      data: "AAAA",
    });
  });
});
