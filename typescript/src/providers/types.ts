export interface ProviderRef {
  id: string;
  expiresAt: number | null;
}

export interface Provider {
  supportsMediaType(mimeType: string): boolean;
  inlineSizeLimit(): number;
  upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef>;
  buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown>;
  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown>;
}

const registry = new Map<string, Provider>();

export function registerProvider(name: string, provider: Provider): void {
  registry.set(name, provider);
}

export function getProvider(name: string): Provider {
  const provider = registry.get(name);
  if (!provider) {
    throw new Error(
      `unknown-provider: "${name}" is not registered. ` +
        `Known providers: ${JSON.stringify([...registry.keys()])}. ` +
        `Register a custom provider with siphon's registerProvider().`
    );
  }
  return provider;
}
