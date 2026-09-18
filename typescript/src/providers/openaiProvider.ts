import { File as NodeBufferFile } from "node:buffer";
import OpenAI, { toFile } from "openai";
import type { Provider, ProviderRef } from "./types.js";

// The openai SDK's toFile() helper requires a global File constructor.
// Node made File a true global starting in v20; on Node 18 (our documented
// minimum) it must be polyfilled from node:buffer. No-op on Node 20+, where
// globalThis.File already exists.
if (typeof (globalThis as { File?: unknown }).File === "undefined") {
  (globalThis as { File?: unknown }).File = NodeBufferFile;
}

const SUPPORTED_PREFIXES = ["image/", "application/pdf", "text/"];
const INLINE_SIZE_LIMIT = 20 * 1024 * 1024;

export class OpenAIProvider implements Provider {
  constructor(private client: OpenAI) {}

  supportsMediaType(mimeType: string): boolean {
    return SUPPORTED_PREFIXES.some((prefix) => mimeType.startsWith(prefix));
  }

  inlineSizeLimit(): number {
    return INLINE_SIZE_LIMIT;
  }

  async upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef> {
    const parts: Buffer[] = [];
    for await (const chunk of chunks) parts.push(chunk);
    const data = Buffer.concat(parts);

    const file = await this.client.files.create({
      file: await toFile(data, "upload", { type: mimeType }),
      purpose: "user_data",
    });

    return { id: file.id, expiresAt: null };
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    const type = mimeType.startsWith("image/") ? "input_image" : "input_file";
    return { type, file_id: ref.id };
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    const dataUrl = `data:${mimeType};base64,${base64Data}`;
    if (mimeType.startsWith("image/")) {
      return { type: "input_image", image_url: dataUrl };
    }
    return { type: "input_file", file_data: dataUrl, filename: "upload" };
  }
}
