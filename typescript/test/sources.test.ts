import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fromAsyncIterable, fromBuffer, fromPath } from "../src/sources.js";

async function collect(source: { chunks(): AsyncIterable<Buffer> }): Promise<Buffer> {
  const parts: Buffer[] = [];
  for await (const chunk of source.chunks()) parts.push(chunk);
  return Buffer.concat(parts);
}

describe("fromBuffer", () => {
  it("is seekable and reproduces content on repeated reads", async () => {
    const data = Buffer.from("hello world".repeat(10));
    const source = fromBuffer(data, "text/plain");

    expect(source.seekable).toBe(true);
    expect(source.size).toBe(data.length);
    expect(await collect(source)).toEqual(data);
    expect(await collect(source)).toEqual(data);
  });
});

describe("fromPath", () => {
  it("reads file content and is re-readable", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "sample.bin");
    const content = Buffer.from(Array.from({ length: 256 }, (_, i) => i).concat(
      Array.from({ length: 256 }, (_, i) => i)
    ));
    await writeFile(filePath, content);

    const source = await fromPath(filePath, "application/octet-stream");

    expect(source.seekable).toBe(true);
    expect(source.size).toBe(content.length);
    expect(await collect(source)).toEqual(content);
    expect(await collect(source)).toEqual(content);
  });

  it("guesses mime type from extension", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "photo.png");
    await writeFile(filePath, Buffer.from([0x89, 0x50, 0x4e, 0x47]));

    const source = await fromPath(filePath);

    expect(source.mimeType).toBe("image/png");
  });

  it("throws when mime type is unknown and not provided", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "mystery.unknownext");
    await writeFile(filePath, Buffer.from("data"));

    await expect(fromPath(filePath)).rejects.toThrow(/mimeType/);
  });
});

describe("fromAsyncIterable", () => {
  it("is not seekable and can only be read once", async () => {
    async function* gen() {
      yield Buffer.from("chunk1");
      yield Buffer.from("chunk2");
    }

    const source = fromAsyncIterable(gen(), "application/octet-stream");

    expect(source.seekable).toBe(false);
    expect(await collect(source)).toEqual(Buffer.from("chunk1chunk2"));
    await expect(collect(source)).rejects.toThrow(/non-seekable/);
  });
});
