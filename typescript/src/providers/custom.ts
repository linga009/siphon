import { randomBytes } from "node:crypto";
import type { Provider, ProviderRef } from "./types.js";

export async function* multipartChunks(
  fieldName: string,
  filename: string,
  mimeType: string,
  chunks: AsyncIterable<Buffer>,
  boundary: string
): AsyncIterable<Buffer> {
  for (const [label, value] of [
    ["fieldName", fieldName],
    ["filename", filename],
    ["mimeType", mimeType],
  ] as const) {
    if (value.includes("\r") || value.includes("\n")) {
      throw new Error(
        `${label} must not contain CR or LF characters (got ${JSON.stringify(value)}); ` +
          "this would allow injecting extra multipart headers or fields."
      );
    }
  }
  const preamble =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\n` +
    `Content-Type: ${mimeType}\r\n\r\n`;
  yield Buffer.from(preamble, "utf-8");
  for await (const chunk of chunks) {
    yield chunk;
  }
  yield Buffer.from(`\r\n--${boundary}--\r\n`, "utf-8");
}

function toWebReadableStream(chunks: AsyncIterable<Buffer>): ReadableStream<Uint8Array> {
  const iterator = chunks[Symbol.asyncIterator]();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { value, done } = await iterator.next();
      if (done) {
        controller.close();
      } else {
        controller.enqueue(value);
      }
    },
  });
}

export class GenericHTTPUploadProvider implements Provider {
  constructor(private uploadUrl: string, private fieldName: string = "file") {}

  supportsMediaType(mimeType: string): boolean {
    return true;
  }

  inlineSizeLimit(): number {
    // Sentinel: 0 (or any non-positive value) means "no declared inline size
    // limit" for this provider, since an arbitrary custom HTTP endpoint has no
    // fixed inline convention to report. This is NOT "zero bytes allowed" --
    // the orchestrator treats any inlineSizeLimit() <= 0 as "unbounded" and
    // skips the inline-size check entirely. Providers with a genuine inline
    // size cap should return a positive byte count instead.
    return 0;
  }

  async upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef> {
    const boundary = `SiphonBoundary${randomBytes(16).toString("hex")}`;
    const body = toWebReadableStream(multipartChunks(this.fieldName, "upload", mimeType, chunks, boundary));

    const response = await fetch(this.uploadUrl, {
      method: "POST",
      headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    if (!response.ok) {
      throw new Error(`Upload to ${this.uploadUrl} failed with status ${response.status}`);
    }
    const data = (await response.json()) as { id: string; expires_at?: number };
    return { id: data.id, expiresAt: data.expires_at ?? null };
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    return { type: "file_reference", id: ref.id };
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    return { type: "inline_base64", mime_type: mimeType, data: base64Data };
  }
}
