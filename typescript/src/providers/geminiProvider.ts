import type { GoogleGenAI } from "@google/genai";
import type { Provider, ProviderRef } from "./types.js";

const SUPPORTED_PREFIXES = ["image/", "audio/", "video/", "application/pdf", "text/"];
const INLINE_SIZE_LIMIT = 20 * 1024 * 1024;

export class GeminiProvider implements Provider {
  constructor(private client: GoogleGenAI) {}

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

    const file = await (this.client as any).files.upload({
      file: new Blob([data], { type: mimeType }),
      config: { mimeType },
    });

    return { id: file.uri, expiresAt: null };
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    return { file_data: { mime_type: mimeType, file_uri: ref.id } };
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    return { inline_data: { mime_type: mimeType, data: base64Data } };
  }
}
