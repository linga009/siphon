import { encodeChunksToBase64 } from "./base64Stream.js";
import { UploadCache } from "./cache.js";
import { TeeHasher, hashChunks } from "./hashing.js";
import type { Provider, ProviderRef } from "./providers/types.js";
import type { MediaSource } from "./sources.js";

export const DEFAULT_SIZE_THRESHOLD = 262144;

async function inlineBlock(
  provider: Provider,
  chunks: AsyncIterable<Buffer>,
  mimeType: string
): Promise<Record<string, unknown>> {
  const base64Data = await encodeChunksToBase64(chunks);
  return provider.buildInlineBlock(base64Data, mimeType);
}

export async function encodeMediaCore(
  provider: Provider,
  providerName: string,
  source: MediaSource,
  cache: UploadCache,
  sizeThreshold: number = DEFAULT_SIZE_THRESHOLD,
  allowInlineFallback = true
): Promise<Record<string, unknown>> {
  const supportsType = provider.supportsMediaType(source.mimeType);

  if (source.seekable) {
    const contentHash = await hashChunks(source.chunks());
    const cached = cache.get(providerName, contentHash);
    if (cached) {
      return provider.buildReferenceBlock(cached, source.mimeType);
    }

    const sizeTriggered = source.size !== null && source.size < sizeThreshold;
    const shouldGoInline = !supportsType || sizeTriggered;
    if (shouldGoInline) {
      if (supportsType && sizeTriggered) {
        const limit = provider.inlineSizeLimit();
        if (limit > 0 && source.size! > limit) {
          throw new Error(
            `Source size (${source.size} bytes) exceeds "${providerName}"'s inlineSizeLimit ` +
              `(${limit} bytes), but it is below sizeThreshold (${sizeThreshold} bytes) so ` +
              `native upload was not attempted. Lower sizeThreshold to at or below the ` +
              `provider's inlineSizeLimit so oversized sources use native upload instead.`
          );
        }
      }
      return inlineBlock(provider, source.chunks(), source.mimeType);
    }

    let ref: ProviderRef;
    try {
      ref = await provider.upload(source.chunks(), source.mimeType);
    } catch (err) {
      if (!allowInlineFallback) throw err;
      console.warn(
        `[siphon] native upload to "${providerName}" failed; falling back to inline base64 ` +
          `(this reintroduces the size/memory overhead Siphon avoids).`,
        err
      );
      return inlineBlock(provider, source.chunks(), source.mimeType);
    }
    cache.put(providerName, contentHash, ref);
    return provider.buildReferenceBlock(ref, source.mimeType);
  }

  if (!supportsType) {
    throw new Error(
      `"${providerName}" does not support media type "${source.mimeType}" and the source is ` +
        `non-seekable, so no inline fallback is possible.`
    );
  }

  const hasher = new TeeHasher();
  async function* tee(): AsyncIterable<Buffer> {
    for await (const chunk of source.chunks()) {
      hasher.update(chunk);
      yield chunk;
    }
  }

  const ref = await provider.upload(tee(), source.mimeType);
  cache.put(providerName, hasher.hexDigest(), ref);
  return provider.buildReferenceBlock(ref, source.mimeType);
}
