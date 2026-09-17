import { describe, expect, it, vi } from "vitest";
import { encodeMedia } from "../../src/api.js";
import { GenericHTTPUploadProvider, multipartChunks } from "../../src/providers/custom.js";
import { registerProvider } from "../../src/providers/types.js";

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

  it("rejects a fieldName containing a newline", async () => {
    await expect(
      collect(
        multipartChunks(
          "file\nX-Injected: evil",
          "photo.png",
          "image/png",
          toAsyncIterable([Buffer.from("AB")]),
          "TESTBOUNDARY"
        )
      )
    ).rejects.toThrow(/CR or LF/);
  });

  it("rejects a mimeType containing a newline", async () => {
    await expect(
      collect(
        multipartChunks(
          "file",
          "photo.png",
          "image/png\r\nX-Injected: evil",
          toAsyncIterable([Buffer.from("AB")]),
          "TESTBOUNDARY"
        )
      )
    ).rejects.toThrow(/CR or LF/);
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

    // The boundary is randomly generated per upload() call (to prevent an
    // attacker-controlled file from injecting multipart form fields via a
    // hardcoded boundary), so extract it from the body rather than asserting
    // a literal value.
    const boundaryMatch = bodyBytes.match(/^--(SiphonBoundary[0-9a-f]{32})\r\n/);
    expect(boundaryMatch).not.toBeNull();
    const boundary = boundaryMatch![1];

    expect(bodyBytes).toBe(
      `--${boundary}\r\n` +
        `Content-Disposition: form-data; name="file"; filename="upload"\r\n` +
        `Content-Type: image/png\r\n\r\n` +
        `ABCD` +
        `\r\n--${boundary}--\r\n`
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

  // README "Custom providers" example, end-to-end through the real encodeMedia/
  // registerProvider path: registerProvider("my-server", new GenericHTTPUploadProvider(...)),
  // then encodeMedia(null, "my-server", <small source>). This is a regression check for the
  // inlineSizeLimit() === 0 sentinel bug: previously this threw for any non-empty source
  // routed to GenericHTTPUploadProvider on the inline path.
  it("inlines a small source through the real encodeMedia path (README custom-providers flow)", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    registerProvider("readme-custom-server", new GenericHTTPUploadProvider("https://my-server/upload"));

    const block = await encodeMedia(null, "readme-custom-server", Buffer.from("tiny clip bytes"), {
      mimeType: "video/mp4",
    });

    expect(block).toEqual({
      type: "inline_base64",
      mime_type: "video/mp4",
      data: Buffer.from("tiny clip bytes").toString("base64"),
    });
    // Small enough to stay under the default size threshold, so it inlines without
    // ever hitting the network.
    expect(fetchMock).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
  });
});
