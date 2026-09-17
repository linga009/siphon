import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { basename } from "node:path";
import { guessMimeType } from "./mimeTypes.js";

const DEFAULT_CHUNK_SIZE = 65536;

export interface MediaSource {
  mimeType: string;
  size: number | null;
  seekable: boolean;
  chunks(): AsyncIterable<Buffer>;
}

export function fromBuffer(data: Buffer, mimeType: string): MediaSource {
  return {
    mimeType,
    size: data.length,
    seekable: true,
    async *chunks() {
      for (let i = 0; i < data.length; i += DEFAULT_CHUNK_SIZE) {
        yield data.subarray(i, i + DEFAULT_CHUNK_SIZE);
      }
    },
  };
}

export async function fromPath(path: string, mimeType?: string): Promise<MediaSource> {
  let resolvedMimeType = mimeType;
  if (!resolvedMimeType) {
    const guessed = guessMimeType(basename(path));
    if (!guessed) {
      throw new Error(
        `Could not guess mimeType for "${basename(path)}"; pass mimeType explicitly.`
      );
    }
    resolvedMimeType = guessed;
  }

  const stats = await stat(path);

  return {
    mimeType: resolvedMimeType,
    size: stats.size,
    seekable: true,
    async *chunks() {
      const stream = createReadStream(path, { highWaterMark: DEFAULT_CHUNK_SIZE });
      for await (const chunk of stream) {
        yield chunk as Buffer;
      }
    },
  };
}

export function fromAsyncIterable(
  it: AsyncIterable<Buffer>,
  mimeType: string,
  size: number | null = null
): MediaSource {
  let consumed = false;

  return {
    mimeType,
    size,
    seekable: false,
    async *chunks() {
      if (consumed) {
        throw new Error(
          "This MediaSource wraps a non-seekable stream and has already been read once."
        );
      }
      consumed = true;
      for await (const chunk of it) {
        yield chunk;
      }
    },
  };
}
