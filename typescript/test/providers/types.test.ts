import { describe, expect, it } from "vitest";
import { getProvider, registerProvider, type Provider, type ProviderRef } from "../../src/providers/types.js";

function makeFakeProvider(): Provider {
  return {
    supportsMediaType: () => true,
    inlineSizeLimit: () => 1024,
    async upload(): Promise<ProviderRef> {
      return { id: "fake-1", expiresAt: null };
    },
    buildReferenceBlock: (ref) => ({ type: "fake", id: ref.id }),
    buildInlineBlock: (data) => ({ type: "fake-inline", data }),
  };
}

describe("provider registry", () => {
  it("round-trips a registered provider", () => {
    const provider = makeFakeProvider();
    registerProvider("fake", provider);
    expect(getProvider("fake")).toBe(provider);
  });

  it("throws a clear error for an unregistered provider", () => {
    expect(() => getProvider("unknown-provider-xyz")).toThrow(/unknown-provider/);
  });
});
