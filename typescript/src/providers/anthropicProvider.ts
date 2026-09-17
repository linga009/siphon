import type Anthropic from "@anthropic-ai/sdk";
import type { Provider, ProviderRef } from "./types.js";

const SUPPORTED_PREFIXES = ["image/", "application/pdf", "text/"];
const INLINE_SIZE_LIMIT = 5 * 1024 * 1024;
const BETA_HEADER = ["files-api-2025-04-14"];

export class AnthropicProvider implements Provider {
  constructor(private client: Anthropic) {}

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

    const file = await this.client.beta.files.upload({
      file: new Blob([data], { type: mimeType }),
      betas: BETA_HEADER,
    });

    return { id: file.id, expiresAt: null };
  }

  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown> {
    const type = mimeType.startsWith("image/") ? "image" : "document";
    return { type, source: { type: "file", file_id: ref.id } };
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    const type = mimeType.startsWith("image/") ? "image" : "document";
    return { type, source: { type: "base64", media_type: mimeType, data: base64Data } };
  }
}
