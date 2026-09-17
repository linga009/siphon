import { UploadCache } from "./cache.js";
import { DEFAULT_SIZE_THRESHOLD, encodeMediaCore } from "./orchestrator.js";
import { getProvider, registerProvider } from "./providers/types.js";
import { fromBuffer, fromPath, type MediaSource } from "./sources.js";

const defaultCache = new UploadCache();

const BUILTIN_PROVIDER_NAMES = new Set(["openai", "anthropic", "gemini"]);

async function ensureBuiltinProviderRegistered(providerName: string, client: unknown): Promise<void> {
  if (!BUILTIN_PROVIDER_NAMES.has(providerName)) return;
  try {
    getProvider(providerName);
    return;
  } catch {
    // not registered yet, fall through
  }

  if (providerName === "openai") {
    const { OpenAIProvider } = await import("./providers/openaiProvider.js");
    registerProvider("openai", new OpenAIProvider(client as any));
  } else if (providerName === "anthropic") {
    const { AnthropicProvider } = await import("./providers/anthropicProvider.js");
    registerProvider("anthropic", new AnthropicProvider(client as any));
  } else if (providerName === "gemini") {
    const { GeminiProvider } = await import("./providers/geminiProvider.js");
    registerProvider("gemini", new GeminiProvider(client as any));
  }
}

async function resolveSource(
  source: string | Buffer | MediaSource,
  mimeType?: string
): Promise<MediaSource> {
  if (typeof source === "object" && "chunks" in source) {
    return source as MediaSource;
  }
  if (Buffer.isBuffer(source)) {
    if (!mimeType) throw new Error("mimeType is required when source is a raw Buffer");
    return fromBuffer(source, mimeType);
  }
  return fromPath(source as string, mimeType);
}

export interface EncodeMediaOptions {
  mimeType?: string;
  sizeThreshold?: number;
  allowInlineFallback?: boolean;
  cache?: UploadCache;
}

export async function encodeMedia(
  client: unknown,
  providerName: string,
  source: string | Buffer | MediaSource,
  options: EncodeMediaOptions = {}
): Promise<Record<string, unknown>> {
  await ensureBuiltinProviderRegistered(providerName, client);
  const provider = getProvider(providerName);
  const mediaSource = await resolveSource(source, options.mimeType);
  return encodeMediaCore(
    provider,
    providerName,
    mediaSource,
    options.cache ?? defaultCache,
    options.sizeThreshold ?? DEFAULT_SIZE_THRESHOLD,
    options.allowInlineFallback ?? true
  );
}
