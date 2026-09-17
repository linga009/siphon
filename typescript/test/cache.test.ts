import { describe, expect, it } from "vitest";
import { UploadCache } from "../src/cache.js";
import type { ProviderRef } from "../src/providers/types.js";

describe("UploadCache", () => {
  it("returns null on a miss", () => {
    const cache = new UploadCache();
    expect(cache.get("openai", "deadbeef")).toBeNull();
  });

  it("returns the ref after put", () => {
    const cache = new UploadCache();
    const ref: ProviderRef = { id: "file-1", expiresAt: null };
    cache.put("openai", "deadbeef", ref);
    expect(cache.get("openai", "deadbeef")).toBe(ref);
  });

  it("is keyed by both provider and hash", () => {
    const cache = new UploadCache();
    cache.put("openai", "deadbeef", { id: "file-1", expiresAt: null });
    expect(cache.get("anthropic", "deadbeef")).toBeNull();
    expect(cache.get("openai", "other-hash")).toBeNull();
  });

  it("treats expired entries as a miss", () => {
    let now = 1000;
    const cache = new UploadCache(() => now);
    cache.put("openai", "deadbeef", { id: "file-1", expiresAt: 1010 });

    now = 1005;
    expect(cache.get("openai", "deadbeef")).not.toBeNull();

    now = 1015;
    expect(cache.get("openai", "deadbeef")).toBeNull();
  });

  it("never expires an entry with expiresAt null", () => {
    let now = 1000;
    const cache = new UploadCache(() => now);
    cache.put("openai", "deadbeef", { id: "file-1", expiresAt: null });

    now = 10_000_000;
    expect(cache.get("openai", "deadbeef")).not.toBeNull();
  });
});
