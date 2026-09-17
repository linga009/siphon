import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { TeeHasher, hashChunks } from "../src/hashing.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

describe("hashChunks", () => {
  it("matches node:crypto sha256 on the full content, for various chunk sizes", async () => {
    const content = Buffer.from("the quick brown fox jumps over the lazy dog".repeat(100));
    const expected = createHash("sha256").update(content).digest("hex");

    for (const chunkSize of [1, 2, 3, 7, 100, 4096]) {
      const chunks: Buffer[] = [];
      for (let i = 0; i < content.length; i += chunkSize) {
        chunks.push(content.subarray(i, i + chunkSize));
      }
      expect(await hashChunks(toAsyncIterable(chunks))).toBe(expected);
    }
  });

  it("hashes an empty iterable the same as an empty buffer", async () => {
    const expected = createHash("sha256").update(Buffer.alloc(0)).digest("hex");
    expect(await hashChunks(toAsyncIterable([]))).toBe(expected);
  });
});

describe("TeeHasher", () => {
  it("matches node:crypto sha256 when updated incrementally", () => {
    const content = Buffer.from("streamed content for incremental hashing");
    const hasher = new TeeHasher();
    for (let i = 0; i < content.length; i += 7) {
      hasher.update(content.subarray(i, i + 7));
    }
    expect(hasher.hexDigest()).toBe(createHash("sha256").update(content).digest("hex"));
  });
});
