import { describe, expect, it } from "vitest";
import { encodeChunksToBase64 } from "../src/base64Stream.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

describe("encodeChunksToBase64", () => {
  it("matches Buffer.toString('base64') across various chunk boundaries", async () => {
    const content = Buffer.from(Array.from({ length: 256 }, (_, i) => i).flatMap((n) => [n, n]));
    const expected = content.toString("base64");

    for (const chunkSize of [1, 2, 3, 7, 100, 4096]) {
      const chunks: Buffer[] = [];
      for (let i = 0; i < content.length; i += chunkSize) {
        chunks.push(content.subarray(i, i + chunkSize));
      }
      expect(await encodeChunksToBase64(toAsyncIterable(chunks))).toBe(expected);
    }
  });

  it("returns an empty string for an empty iterable", async () => {
    expect(await encodeChunksToBase64(toAsyncIterable([]))).toBe("");
  });
});
