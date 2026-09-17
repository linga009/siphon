import type { ProviderRef } from "./providers/types.js";

export class UploadCache {
  private entries = new Map<string, ProviderRef>();

  constructor(private clock: () => number = () => Date.now() / 1000) {}

  get(providerName: string, contentHash: string): ProviderRef | null {
    const key = `${providerName}:${contentHash}`;
    const ref = this.entries.get(key);
    if (!ref) return null;
    if (ref.expiresAt !== null && ref.expiresAt <= this.clock()) {
      this.entries.delete(key);
      return null;
    }
    return ref;
  }

  put(providerName: string, contentHash: string, ref: ProviderRef): void {
    this.entries.set(`${providerName}:${contentHash}`, ref);
  }
}
