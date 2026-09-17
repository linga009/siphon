import { encodeChunksToBase64 } from "./base64Stream.js";
import { UploadCache } from "./cache.js";
import { TeeHasher, hashChunks } from "./hashing.js";
import type { Provider } from "./providers/types.js";
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

    const shouldGoInline =
      !supportsType || (source.size !== null && source.size < sizeThreshold);
    if (shouldGoInline) {
      return inlineBlock(provider, source.chunks(), source.mimeType);
    }

    try {
      const ref = await provider.upload(source.chunks(), source.mimeType);
      cache.put(providerName, contentHash, ref);
      return provider.buildReferenceBlock(ref, source.mimeType);
    } catch (err) {
      console.warn(
        `[siphon] native upload to "${providerName}" failed; falling back to inline base64 ` +
          `(this reintroduces the size/memory overhead Siphon avoids).`,
        err
      );
      if (!allowInlineFallback) throw err;
      return inlineBlock(provider, source.chunks(), source.mimeType);
    }
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
