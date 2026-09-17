# Siphon (TypeScript) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the TypeScript `siphon` package for Node.js: a client-side library that replaces inline Base64 for multimodal LLM API calls with native provider file-upload APIs (OpenAI, Anthropic, Gemini), a pluggable custom-provider extension point, streaming uploads, content-hash caching, and a size-threshold fallback to inline Base64.

**Architecture:** Identical in shape to the sibling Python package (see `docs/superpowers/specs/2026-09-17-siphon-design.md` and `docs/superpowers/plans/2026-09-17-siphon-python.md`) but implemented independently in idiomatic TypeScript/Node. A `MediaSource` turns a file path, an in-memory `Buffer`, or an arbitrary async iterable into a uniform `AsyncIterable<Buffer>` plus metadata. An orchestrator checks an in-memory cache, applies a size threshold, and either streams into a `Provider` adapter's native upload or inline-encodes with a streaming Base64 encoder.

**Tech Stack:** Node.js >=18, TypeScript >=5.4, `vitest` for tests, official SDKs (`openai`, `@anthropic-ai/sdk`, `@google/genai`) as **optional peer dependencies**.

## Global Constraints

- Node.js >=18 (for built-in `fetch`, `ReadableStream`, and streaming request bodies with `duplex: "half"`).
- No real network calls in unit tests — all provider SDK calls are mocked with `vi.fn()`/`vi.mocked()`. Real-API integration tests are out of scope for this plan (same as the Python plan).
- Default inline-vs-upload size threshold: 262144 bytes (256 KiB), overridable per call.
- Cache key: `` `${providerName}:${contentHash}` ``, content hash is SHA-256 via Node's built-in `node:crypto` (matches the Python plan's choice, no extra dependency).
- Every fallback-to-inline event (excluding the plain size-threshold path) logs via `console.warn` prefixed `"[siphon]"`.
- Node's async-by-default I/O model means there is **no separate sync API surface** in TypeScript (unlike Python, which mirrors the official SDKs' sync/async client split) — `encodeMedia` is the only public entry point and is always `async`.
- Package layout: this repo's `typescript/` directory, sibling to `python/`. Package name `siphon` on npm (same name as the PyPI package — different registries, no collision).

---

## File Structure

```
typescript/
  package.json
  tsconfig.json
  vitest.config.ts
  src/
    hashing.ts             # streaming SHA-256 helper
    mimeTypes.ts             # tiny extension -> mime-type lookup (no dependency)
    sources.ts                # MediaSource: path / Buffer / async iterable
    base64Stream.ts            # chunked base64 inline encoder
    providers/
      types.ts                 # Provider interface, ProviderRef, registry
      openaiProvider.ts
      anthropicProvider.ts
      geminiProvider.ts
      custom.ts                  # generic streaming multipart uploader
    cache.ts                      # UploadCache (in-memory, expiry-aware)
    orchestrator.ts                 # decision logic (single async implementation)
    api.ts                           # encodeMedia / registerProvider
    index.ts                          # public exports
  test/
    hashing.test.ts
    sources.test.ts
    base64Stream.test.ts
    cache.test.ts
    providers/openaiProvider.test.ts
    providers/anthropicProvider.test.ts
    providers/geminiProvider.test.ts
    providers/custom.test.ts
    orchestrator.test.ts
    api.test.ts
  README.md
```

---

### Task 1: Project scaffolding + streaming content hasher

**Files:**
- Create: `typescript/package.json`
- Create: `typescript/tsconfig.json`
- Create: `typescript/vitest.config.ts`
- Create: `typescript/src/hashing.ts`
- Test: `typescript/test/hashing.test.ts`

**Interfaces:**
- Produces:
  - `async function hashChunks(chunks: AsyncIterable<Buffer>): Promise<string>` — hex SHA-256 digest of the concatenated chunks, without buffering them all in memory at once.
  - `class TeeHasher` — `.update(chunk: Buffer): void`, `.hexDigest(): string`, for incremental hashing interleaved with other async work.

- [ ] **Step 1: Create the package scaffolding**

Create `typescript/package.json`:

```json
{
  "name": "siphon",
  "version": "0.1.0",
  "description": "Stream binary media to multimodal LLM APIs without Base64.",
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "engines": { "node": ">=18" },
  "scripts": {
    "build": "tsc -p tsconfig.json",
    "test": "vitest run"
  },
  "peerDependencies": {
    "openai": ">=4.60.0",
    "@anthropic-ai/sdk": ">=0.30.0",
    "@google/genai": ">=0.3.0"
  },
  "peerDependenciesMeta": {
    "openai": { "optional": true },
    "@anthropic-ai/sdk": { "optional": true },
    "@google/genai": { "optional": true }
  },
  "devDependencies": {
    "typescript": "^5.6.0",
    "vitest": "^2.1.0",
    "@types/node": "^22.0.0",
    "openai": ">=4.60.0",
    "@anthropic-ai/sdk": ">=0.30.0",
    "@google/genai": ">=0.3.0"
  }
}
```

Create `typescript/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "declaration": true,
    "outDir": "dist",
    "rootDir": "src",
    "esModuleInterop": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

Create `typescript/vitest.config.ts`:

```typescript
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["test/**/*.test.ts"],
  },
});
```

- [ ] **Step 2: Write the failing test for the streaming hasher**

Create `typescript/test/hashing.test.ts`:

```typescript
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { TeeHasher, hashChunks } from "../src/hashing.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

describe("hashChunks", () => {
  it("matches node:crypto sha256 on the full content, for various chunk sizes", async () => {
    const content = Buffer.from("the quick brown fox jumps over the lazy dog".repeat(100));
    const expected = createHash("sha256").update(content).digest("hex");

    for (const chunkSize of [1, 2, 3, 7, 100, 4096]) {
      const chunks: Buffer[] = [];
      for (let i = 0; i < content.length; i += chunkSize) {
        chunks.push(content.subarray(i, i + chunkSize));
      }
      expect(await hashChunks(toAsyncIterable(chunks))).toBe(expected);
    }
  });

  it("hashes an empty iterable the same as an empty buffer", async () => {
    const expected = createHash("sha256").update(Buffer.alloc(0)).digest("hex");
    expect(await hashChunks(toAsyncIterable([]))).toBe(expected);
  });
});

describe("TeeHasher", () => {
  it("matches node:crypto sha256 when updated incrementally", () => {
    const content = Buffer.from("streamed content for incremental hashing");
    const hasher = new TeeHasher();
    for (let i = 0; i < content.length; i += 7) {
      hasher.update(content.subarray(i, i + 7));
    }
    expect(hasher.hexDigest()).toBe(createHash("sha256").update(content).digest("hex"));
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd typescript && npm install && npx vitest run test/hashing.test.ts`
Expected: FAIL — cannot find module `../src/hashing.js`

- [ ] **Step 4: Implement the hasher**

Create `typescript/src/hashing.ts`:

```typescript
import { createHash, type Hash } from "node:crypto";

export class TeeHasher {
  private hash: Hash = createHash("sha256");

  update(chunk: Buffer): void {
    this.hash.update(chunk);
  }

  hexDigest(): string {
    return this.hash.copy().digest("hex");
  }
}

export async function hashChunks(chunks: AsyncIterable<Buffer>): Promise<string> {
  const hasher = new TeeHasher();
  for await (const chunk of chunks) {
    hasher.update(chunk);
  }
  return hasher.hexDigest();
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd typescript && npx vitest run test/hashing.test.ts`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add typescript/package.json typescript/tsconfig.json typescript/vitest.config.ts typescript/src/hashing.ts typescript/test/hashing.test.ts
git commit -m "feat(typescript): add package scaffolding and streaming content hasher"
```

---

### Task 2: MIME type lookup + MediaSource abstraction

**Files:**
- Create: `typescript/src/mimeTypes.ts`
- Create: `typescript/src/sources.ts`
- Test: `typescript/test/sources.test.ts`

**Interfaces:**
- Produces (`mimeTypes.ts`): `function guessMimeType(filename: string): string | null` — extension-based lookup covering `png, jpg, jpeg, gif, webp, pdf, mp3, mp4, wav, mov, txt`.
- Produces (`sources.ts`):
  - `interface MediaSource { mimeType: string; size: number | null; seekable: boolean; chunks(): AsyncIterable<Buffer>; }`
  - `function fromBuffer(data: Buffer, mimeType: string): MediaSource` — seekable.
  - `async function fromPath(path: string, mimeType?: string): Promise<MediaSource>` — seekable (uses `fs.createReadStream` fresh on each `chunks()` call); throws if `mimeType` isn't given and can't be guessed.
  - `function fromAsyncIterable(it: AsyncIterable<Buffer>, mimeType: string, size?: number | null): MediaSource` — non-seekable; calling `.chunks()` a second time throws.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/sources.test.ts`:

```typescript
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fromAsyncIterable, fromBuffer, fromPath } from "../src/sources.js";

async function collect(source: { chunks(): AsyncIterable<Buffer> }): Promise<Buffer> {
  const parts: Buffer[] = [];
  for await (const chunk of source.chunks()) parts.push(chunk);
  return Buffer.concat(parts);
}

describe("fromBuffer", () => {
  it("is seekable and reproduces content on repeated reads", async () => {
    const data = Buffer.from("hello world".repeat(10));
    const source = fromBuffer(data, "text/plain");

    expect(source.seekable).toBe(true);
    expect(source.size).toBe(data.length);
    expect(await collect(source)).toEqual(data);
    expect(await collect(source)).toEqual(data);
  });
});

describe("fromPath", () => {
  it("reads file content and is re-readable", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "sample.bin");
    const content = Buffer.from(Array.from({ length: 256 }, (_, i) => i).concat(
      Array.from({ length: 256 }, (_, i) => i)
    ));
    await writeFile(filePath, content);

    const source = await fromPath(filePath, "application/octet-stream");

    expect(source.seekable).toBe(true);
    expect(source.size).toBe(content.length);
    expect(await collect(source)).toEqual(content);
    expect(await collect(source)).toEqual(content);
  });

  it("guesses mime type from extension", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "photo.png");
    await writeFile(filePath, Buffer.from([0x89, 0x50, 0x4e, 0x47]));

    const source = await fromPath(filePath);

    expect(source.mimeType).toBe("image/png");
  });

  it("throws when mime type is unknown and not provided", async () => {
    const dir = await mkdtemp(join(tmpdir(), "siphon-test-"));
    const filePath = join(dir, "mystery.unknownext");
    await writeFile(filePath, Buffer.from("data"));

    await expect(fromPath(filePath)).rejects.toThrow(/mimeType/);
  });
});

describe("fromAsyncIterable", () => {
  it("is not seekable and can only be read once", async () => {
    async function* gen() {
      yield Buffer.from("chunk1");
      yield Buffer.from("chunk2");
    }

    const source = fromAsyncIterable(gen(), "application/octet-stream");

    expect(source.seekable).toBe(false);
    expect(await collect(source)).toEqual(Buffer.from("chunk1chunk2"));
    await expect(collect(source)).rejects.toThrow(/non-seekable/);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/sources.test.ts`
Expected: FAIL — cannot find module `../src/sources.js`

- [ ] **Step 3: Implement `mimeTypes.ts` and `sources.ts`**

Create `typescript/src/mimeTypes.ts`:

```typescript
const EXTENSION_TO_MIME: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".webp": "image/webp",
  ".pdf": "application/pdf",
  ".mp3": "audio/mpeg",
  ".wav": "audio/wav",
  ".mp4": "video/mp4",
  ".mov": "video/quicktime",
  ".txt": "text/plain",
};

export function guessMimeType(filename: string): string | null {
  const dot = filename.lastIndexOf(".");
  if (dot === -1) return null;
  const ext = filename.slice(dot).toLowerCase();
  return EXTENSION_TO_MIME[ext] ?? null;
}
```

Create `typescript/src/sources.ts`:

```typescript
import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { basename } from "node:path";
import { guessMimeType } from "./mimeTypes.js";

const DEFAULT_CHUNK_SIZE = 65536;

export interface MediaSource {
  mimeType: string;
  size: number | null;
  seekable: boolean;
  chunks(): AsyncIterable<Buffer>;
}

export function fromBuffer(data: Buffer, mimeType: string): MediaSource {
  return {
    mimeType,
    size: data.length,
    seekable: true,
    async *chunks() {
      for (let i = 0; i < data.length; i += DEFAULT_CHUNK_SIZE) {
        yield data.subarray(i, i + DEFAULT_CHUNK_SIZE);
      }
    },
  };
}

export async function fromPath(path: string, mimeType?: string): Promise<MediaSource> {
  let resolvedMimeType = mimeType;
  if (!resolvedMimeType) {
    const guessed = guessMimeType(basename(path));
    if (!guessed) {
      throw new Error(
        `Could not guess mimeType for "${basename(path)}"; pass mimeType explicitly.`
      );
    }
    resolvedMimeType = guessed;
  }

  const stats = await stat(path);

  return {
    mimeType: resolvedMimeType,
    size: stats.size,
    seekable: true,
    async *chunks() {
      const stream = createReadStream(path, { highWaterMark: DEFAULT_CHUNK_SIZE });
      for await (const chunk of stream) {
        yield chunk as Buffer;
      }
    },
  };
}

export function fromAsyncIterable(
  it: AsyncIterable<Buffer>,
  mimeType: string,
  size: number | null = null
): MediaSource {
  let consumed = false;

  return {
    mimeType,
    size,
    seekable: false,
    async *chunks() {
      if (consumed) {
        throw new Error(
          "This MediaSource wraps a non-seekable stream and has already been read once."
        );
      }
      consumed = true;
      for await (const chunk of it) {
        yield chunk;
      }
    },
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/sources.test.ts`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/mimeTypes.ts typescript/src/sources.ts typescript/test/sources.test.ts
git commit -m "feat(typescript): add MediaSource abstraction for paths, buffers, and streams"
```

---

### Task 3: Streaming Base64 inline encoder

**Files:**
- Create: `typescript/src/base64Stream.ts`
- Test: `typescript/test/base64Stream.test.ts`

**Interfaces:**
- Produces: `async function encodeChunksToBase64(chunks: AsyncIterable<Buffer>): Promise<string>` — full standard Base64 string, encoded from fixed-size 3-byte-aligned groups incrementally (a small carried remainder, never the whole buffer).

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/base64Stream.test.ts`:

```typescript
import { describe, expect, it } from "vitest";
import { encodeChunksToBase64 } from "../src/base64Stream.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

describe("encodeChunksToBase64", () => {
  it("matches Buffer.toString('base64') across various chunk boundaries", async () => {
    const content = Buffer.from(Array.from({ length: 256 }, (_, i) => i).flatMap((n) => [n, n]));
    const expected = content.toString("base64");

    for (const chunkSize of [1, 2, 3, 7, 100, 4096]) {
      const chunks: Buffer[] = [];
      for (let i = 0; i < content.length; i += chunkSize) {
        chunks.push(content.subarray(i, i + chunkSize));
      }
      expect(await encodeChunksToBase64(toAsyncIterable(chunks))).toBe(expected);
    }
  });

  it("returns an empty string for an empty iterable", async () => {
    expect(await encodeChunksToBase64(toAsyncIterable([]))).toBe("");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/base64Stream.test.ts`
Expected: FAIL — cannot find module `../src/base64Stream.js`

- [ ] **Step 3: Implement `base64Stream.ts`**

Create `typescript/src/base64Stream.ts`:

```typescript
export async function encodeChunksToBase64(chunks: AsyncIterable<Buffer>): Promise<string> {
  const parts: string[] = [];
  let remainder = Buffer.alloc(0);

  for await (const chunk of chunks) {
    const buffer = Buffer.concat([remainder, chunk]);
    const usableLength = Math.floor(buffer.length / 3) * 3;
    const usable = buffer.subarray(0, usableLength);
    remainder = buffer.subarray(usableLength);
    if (usable.length > 0) {
      parts.push(usable.toString("base64"));
    }
  }

  if (remainder.length > 0) {
    parts.push(remainder.toString("base64"));
  }

  return parts.join("");
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/base64Stream.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/base64Stream.ts typescript/test/base64Stream.test.ts
git commit -m "feat(typescript): add streaming base64 encoder for inline fallback"
```

---

### Task 4: Provider interface, ProviderRef, and registry

**Files:**
- Create: `typescript/src/providers/types.ts`
- Test: `typescript/test/providers/types.test.ts`

**Interfaces:**
- Produces:
  - `interface ProviderRef { id: string; expiresAt: number | null; }`
  - `interface Provider { supportsMediaType(mimeType: string): boolean; inlineSizeLimit(): number; upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef>; buildReferenceBlock(ref: ProviderRef, mimeType: string): Record<string, unknown>; buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown>; }`
  - `function registerProvider(name: string, provider: Provider): void`
  - `function getProvider(name: string): Provider` — throws a clear `Error` if unregistered.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/providers/types.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/providers/types.test.ts`
Expected: FAIL — cannot find module `../../src/providers/types.js`

- [ ] **Step 3: Implement `providers/types.ts`**

Create `typescript/src/providers/types.ts`:

```typescript
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/providers/types.test.ts`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/providers/types.ts typescript/test/providers/types.test.ts
git commit -m "feat(typescript): add Provider interface, ProviderRef, and registry"
```

---

### Task 5: In-memory upload cache

**Files:**
- Create: `typescript/src/cache.ts`
- Test: `typescript/test/cache.test.ts`

**Interfaces:**
- Consumes: `ProviderRef` from Task 4.
- Produces: `class UploadCache`:
  - `constructor(clock: () => number = () => Date.now() / 1000)`
  - `get(providerName: string, contentHash: string): ProviderRef | null`
  - `put(providerName: string, contentHash: string, ref: ProviderRef): void`

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/cache.test.ts`:

```typescript
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/cache.test.ts`
Expected: FAIL — cannot find module `../src/cache.js`

- [ ] **Step 3: Implement `cache.ts`**

Create `typescript/src/cache.ts`:

```typescript
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/cache.test.ts`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/cache.ts typescript/test/cache.test.ts
git commit -m "feat(typescript): add in-memory expiry-aware upload cache"
```

---

### Task 6: OpenAI provider adapter

**Files:**
- Create: `typescript/src/providers/openaiProvider.ts`
- Test: `typescript/test/providers/openaiProvider.test.ts`

**Interfaces:**
- Produces: `class OpenAIProvider implements Provider`, constructor `new OpenAIProvider(client: OpenAI)`.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/providers/openaiProvider.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { OpenAIProvider } from "../../src/providers/openaiProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(fileId: string) {
  return {
    files: {
      create: vi.fn().mockResolvedValue({ id: fileId }),
    },
  } as any;
}

describe("OpenAIProvider", () => {
  it("supports images and PDFs but not audio", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/png")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("audio/mpeg")).toBe(false);
  });

  it("uploads via files.create with purpose user_data", async () => {
    const client = makeFakeClient("file-xyz");
    const provider = new OpenAIProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("hello")]), "image/png");

    expect(ref).toEqual({ id: "file-xyz", expiresAt: null });
    expect(client.files.create).toHaveBeenCalledTimes(1);
    const callArgs = client.files.create.mock.calls[0][0];
    expect(callArgs.purpose).toBe("user_data");
  });

  it("builds an input_image reference block for images", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildReferenceBlock({ id: "file-1", expiresAt: null }, "image/png")).toEqual({
      type: "input_image",
      file_id: "file-1",
    });
  });

  it("builds an input_file reference block for PDFs", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "file-2", expiresAt: null }, "application/pdf")
    ).toEqual({ type: "input_file", file_id: "file-2" });
  });

  it("wraps raw base64 in a data URL for inline images", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "input_image",
      image_url: "data:image/png;base64,AAAA",
    });
  });

  it("wraps raw base64 in file_data for inline PDFs", () => {
    const provider = new OpenAIProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "application/pdf")).toEqual({
      type: "input_file",
      file_data: "data:application/pdf;base64,AAAA",
      filename: "upload",
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/providers/openaiProvider.test.ts`
Expected: FAIL — cannot find module `../../src/providers/openaiProvider.js`

- [ ] **Step 3: Implement `providers/openaiProvider.ts`**

Create `typescript/src/providers/openaiProvider.ts`:

```typescript
import OpenAI, { toFile } from "openai";
import type { Provider, ProviderRef } from "./types.js";

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
```

**Note:** like the Python adapter, `upload()` currently buffers the full payload into one `Buffer` before calling `toFile()`, because the OpenAI Node SDK's upload helper expects a complete buffer/stream-like object rather than an arbitrary async generator. This is the same documented, intentional limitation as the Python plan — see the README task at the end of this plan.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/providers/openaiProvider.test.ts`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/providers/openaiProvider.ts typescript/test/providers/openaiProvider.test.ts
git commit -m "feat(typescript): add OpenAI provider adapter"
```

---

### Task 7: Anthropic provider adapter

**Files:**
- Create: `typescript/src/providers/anthropicProvider.ts`
- Test: `typescript/test/providers/anthropicProvider.test.ts`

**Interfaces:**
- Produces: `class AnthropicProvider implements Provider`, constructor `new AnthropicProvider(client: Anthropic)`.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/providers/anthropicProvider.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { AnthropicProvider } from "../../src/providers/anthropicProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(fileId: string) {
  return {
    beta: {
      files: {
        upload: vi.fn().mockResolvedValue({ id: fileId }),
      },
    },
  } as any;
}

describe("AnthropicProvider", () => {
  it("supports images and PDFs but not video", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/jpeg")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("video/mp4")).toBe(false);
  });

  it("uploads via beta.files.upload with the files-api beta header", async () => {
    const client = makeFakeClient("file_011xyz");
    const provider = new AnthropicProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("abc")]), "image/png");

    expect(ref).toEqual({ id: "file_011xyz", expiresAt: null });
    expect(client.beta.files.upload).toHaveBeenCalledTimes(1);
    const options = client.beta.files.upload.mock.calls[0][1];
    expect(options.betas).toEqual(["files-api-2025-04-14"]);
  });

  it("builds an image reference block", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.buildReferenceBlock({ id: "file_1", expiresAt: null }, "image/png")).toEqual({
      type: "image",
      source: { type: "file", file_id: "file_1" },
    });
  });

  it("builds a document reference block for PDFs", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "file_2", expiresAt: null }, "application/pdf")
    ).toEqual({ type: "document", source: { type: "file", file_id: "file_2" } });
  });

  it("builds an inline base64 image block", () => {
    const provider = new AnthropicProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "image",
      source: { type: "base64", media_type: "image/png", data: "AAAA" },
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/providers/anthropicProvider.test.ts`
Expected: FAIL — cannot find module `../../src/providers/anthropicProvider.js`

- [ ] **Step 3: Implement `providers/anthropicProvider.ts`**

Create `typescript/src/providers/anthropicProvider.ts`:

```typescript
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

    const file = await (this.client as any).beta.files.upload(
      { file: new Blob([data], { type: mimeType }) },
      { betas: BETA_HEADER }
    );

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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/providers/anthropicProvider.test.ts`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/providers/anthropicProvider.ts typescript/test/providers/anthropicProvider.test.ts
git commit -m "feat(typescript): add Anthropic provider adapter"
```

---

### Task 8: Gemini provider adapter

**Files:**
- Create: `typescript/src/providers/geminiProvider.ts`
- Test: `typescript/test/providers/geminiProvider.test.ts`

**Interfaces:**
- Produces: `class GeminiProvider implements Provider`, constructor `new GeminiProvider(client: GoogleGenAI)`.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/providers/geminiProvider.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { GeminiProvider } from "../../src/providers/geminiProvider.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

function makeFakeClient(uri: string) {
  return {
    files: {
      upload: vi.fn().mockResolvedValue({ uri }),
    },
  } as any;
}

describe("GeminiProvider", () => {
  it("supports images, audio, video, and PDFs but not arbitrary binaries", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(provider.supportsMediaType("image/png")).toBe(true);
    expect(provider.supportsMediaType("audio/mp3")).toBe(true);
    expect(provider.supportsMediaType("video/mp4")).toBe(true);
    expect(provider.supportsMediaType("application/pdf")).toBe(true);
    expect(provider.supportsMediaType("application/zip")).toBe(false);
  });

  it("uploads via files.upload and uses the returned uri as the ref id", async () => {
    const client = makeFakeClient("https://example/files/xyz");
    const provider = new GeminiProvider(client);

    const ref = await provider.upload(toAsyncIterable([Buffer.from("abc")]), "image/png");

    expect(ref).toEqual({ id: "https://example/files/xyz", expiresAt: null });
    expect(client.files.upload).toHaveBeenCalledTimes(1);
  });

  it("builds a reference block using file_data with the uri", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(
      provider.buildReferenceBlock({ id: "https://example/files/1", expiresAt: null }, "image/png")
    ).toEqual({ file_data: { mime_type: "image/png", file_uri: "https://example/files/1" } });
  });

  it("builds an inline_data block", () => {
    const provider = new GeminiProvider(makeFakeClient("x"));
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      inline_data: { mime_type: "image/png", data: "AAAA" },
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/providers/geminiProvider.test.ts`
Expected: FAIL — cannot find module `../../src/providers/geminiProvider.js`

- [ ] **Step 3: Implement `providers/geminiProvider.ts`**

Create `typescript/src/providers/geminiProvider.ts`:

```typescript
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/providers/geminiProvider.test.ts`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/providers/geminiProvider.ts typescript/test/providers/geminiProvider.test.ts
git commit -m "feat(typescript): add Gemini provider adapter"
```

---

### Task 9: Orchestrator

**Files:**
- Create: `typescript/src/orchestrator.ts`
- Test: `typescript/test/orchestrator.test.ts`

**Interfaces:**
- Consumes: `MediaSource` (Task 2), `hashChunks`/`TeeHasher` (Task 1), `encodeChunksToBase64` (Task 3), `Provider`/`ProviderRef` (Task 4), `UploadCache` (Task 5).
- Produces: `async function encodeMediaCore(provider: Provider, providerName: string, source: MediaSource, cache: UploadCache, sizeThreshold = 262144, allowInlineFallback = true): Promise<Record<string, unknown>>` — same behavior contract as the Python plan's `encode_media_sync`/`encode_media_async` (they collapse into one function here since TS has no separate sync API — see Global Constraints).

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/orchestrator.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { UploadCache } from "../src/cache.js";
import { encodeMediaCore } from "../src/orchestrator.js";
import type { Provider, ProviderRef } from "../src/providers/types.js";
import { fromAsyncIterable, fromBuffer } from "../src/sources.js";

class RecordingProvider implements Provider {
  uploadCalls = 0;
  uploadedBytes = Buffer.alloc(0);

  constructor(private supports = true, private raiseOnUpload = false) {}

  supportsMediaType(): boolean {
    return this.supports;
  }

  inlineSizeLimit(): number {
    return 10_000_000;
  }

  async upload(chunks: AsyncIterable<Buffer>): Promise<ProviderRef> {
    this.uploadCalls += 1;
    const parts: Buffer[] = [];
    for await (const chunk of chunks) parts.push(chunk);
    this.uploadedBytes = Buffer.concat([this.uploadedBytes, ...parts]);
    if (this.raiseOnUpload) throw new Error("upload failed");
    return { id: `ref-${this.uploadCalls}`, expiresAt: null };
  }

  buildReferenceBlock(ref: ProviderRef): Record<string, unknown> {
    return { type: "ref", id: ref.id };
  }

  buildInlineBlock(data: string): Record<string, unknown> {
    return { type: "inline", data };
  }
}

describe("encodeMediaCore", () => {
  it("goes inline for a small seekable source without calling upload", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.from("tiny"), "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(provider.uploadCalls).toBe(0);
  });

  it("uploads and caches a large seekable source", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(2000, "x");
    const source = fromBuffer(content, "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block).toEqual({ type: "ref", id: "ref-1" });
    expect(provider.uploadCalls).toBe(1);
    expect(provider.uploadedBytes).toEqual(content);
  });

  it("hits the cache on a second call with identical content and does not re-upload", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(2000, "y");

    const block1 = await encodeMediaCore(
      provider,
      "fake",
      fromBuffer(content, "image/png"),
      cache,
      1000
    );
    const block2 = await encodeMediaCore(
      provider,
      "fake",
      fromBuffer(content, "image/png"),
      cache,
      1000
    );

    expect(block1).toEqual(block2);
    expect(provider.uploadCalls).toBe(1);
  });

  it("goes inline for an unsupported media type even if large", async () => {
    const provider = new RecordingProvider(false);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "application/weird");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(provider.uploadCalls).toBe(0);
  });

  it("falls back to inline when upload fails and fallback is allowed", async () => {
    const provider = new RecordingProvider(true, true);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "image/png");
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block.type).toBe("inline");
    expect(warnSpy).toHaveBeenCalled();
    warnSpy.mockRestore();
  });

  it("re-throws when upload fails and fallback is disabled", async () => {
    const provider = new RecordingProvider(true, true);
    const cache = new UploadCache();
    const source = fromBuffer(Buffer.alloc(5000, "x"), "image/png");
    vi.spyOn(console, "warn").mockImplementation(() => {});

    await expect(encodeMediaCore(provider, "fake", source, cache, 1000, false)).rejects.toThrow(
      "upload failed"
    );
  });

  it("uploads a non-seekable source and populates the cache after success", async () => {
    const provider = new RecordingProvider();
    const cache = new UploadCache();
    const content = Buffer.alloc(5000, "z");
    async function* gen() {
      for (let i = 0; i < content.length; i += 100) yield content.subarray(i, i + 100);
    }
    const source = fromAsyncIterable(gen(), "image/png");

    const block = await encodeMediaCore(provider, "fake", source, cache, 1000);

    expect(block).toEqual({ type: "ref", id: "ref-1" });
    expect(provider.uploadedBytes).toEqual(content);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/orchestrator.test.ts`
Expected: FAIL — cannot find module `../src/orchestrator.js`

- [ ] **Step 3: Implement `orchestrator.ts`**

Create `typescript/src/orchestrator.ts`:

```typescript
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/orchestrator.test.ts`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/orchestrator.ts typescript/test/orchestrator.test.ts
git commit -m "feat(typescript): add orchestrator with cache, threshold, and fallback logic"
```

---

### Task 10: Public API and package exports

**Files:**
- Create: `typescript/src/api.ts`
- Create: `typescript/src/index.ts`
- Test: `typescript/test/api.test.ts`

**Interfaces:**
- Consumes: `encodeMediaCore` (Task 9), `Provider`/`registerProvider`/`getProvider` (Task 4), `MediaSource`/`fromPath`/`fromBuffer`/`fromAsyncIterable` (Task 2), `OpenAIProvider`/`AnthropicProvider`/`GeminiProvider` (Tasks 6-8).
- Produces (public package surface):
  - `async function encodeMedia(client: unknown, providerName: string, source: string | Buffer | MediaSource, options?: { mimeType?: string; sizeThreshold?: number; allowInlineFallback?: boolean; cache?: UploadCache }): Promise<Record<string, unknown>>`
  - Re-exports: `registerProvider`, `getProvider`, `fromPath`, `fromBuffer`, `fromAsyncIterable`, `MediaSource`, `Provider`, `ProviderRef`, `UploadCache`.
  - Built-in provider names `"openai"`, `"anthropic"`, `"gemini"` are lazily constructed and registered the first time `encodeMedia` is called with that `providerName`, wrapping whichever `client` was passed — no eager import of any SDK at module load time.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/api.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { encodeMedia } from "../src/api.js";
import { registerProvider } from "../src/providers/types.js";
import * as siphon from "../src/index.js";

describe("encodeMedia", () => {
  it("accepts a raw Buffer source and inline-encodes a small payload", async () => {
    registerProvider("stub", {
      supportsMediaType: () => true,
      inlineSizeLimit: () => 10_000_000,
      async upload(): Promise<never> {
        throw new Error("should not upload");
      },
      buildReferenceBlock: () => ({ type: "ref" }),
      buildInlineBlock: (data) => ({ type: "inline", data }),
    });

    const block = await encodeMedia(null, "stub", Buffer.from("tiny"), {
      mimeType: "text/plain",
    });

    expect(block.type).toBe("inline");
  });

  it("throws a clear error for an unregistered provider", async () => {
    await expect(
      encodeMedia(null, "totally-unknown-provider-xyz", Buffer.from("x"), {
        mimeType: "text/plain",
      })
    ).rejects.toThrow(/unknown-provider/);
  });

  it("builds an OpenAIProvider when providerName is openai", async () => {
    const client = {
      files: { create: vi.fn().mockResolvedValue({ id: "file-1" }) },
    } as any;

    const block = await encodeMedia(client, "openai", Buffer.alloc(500_000, "x"), {
      mimeType: "image/png",
      sizeThreshold: 1000,
    });

    expect(block).toEqual({ type: "input_image", file_id: "file-1" });
  });

  it("re-exports the expected public names from index.ts", () => {
    expect(typeof siphon.encodeMedia).toBe("function");
    expect(typeof siphon.registerProvider).toBe("function");
    expect(typeof siphon.fromPath).toBe("function");
    expect(typeof siphon.fromBuffer).toBe("function");
    expect(typeof siphon.fromAsyncIterable).toBe("function");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/api.test.ts`
Expected: FAIL — cannot find module `../src/api.js`

- [ ] **Step 3: Implement `api.ts` and `index.ts`**

Create `typescript/src/api.ts`:

```typescript
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
```

Create `typescript/src/index.ts`:

```typescript
export { encodeMedia, type EncodeMediaOptions } from "./api.js";
export { UploadCache } from "./cache.js";
export { getProvider, registerProvider, type Provider, type ProviderRef } from "./providers/types.js";
export { fromAsyncIterable, fromBuffer, fromPath, type MediaSource } from "./sources.js";
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/api.test.ts`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/api.ts typescript/src/index.ts typescript/test/api.test.ts
git commit -m "feat(typescript): add public encodeMedia API and package exports"
```

---

### Task 11: Custom provider extension point + generic streaming multipart uploader

**Files:**
- Create: `typescript/src/providers/custom.ts`
- Test: `typescript/test/providers/custom.test.ts`

**Interfaces:**
- Produces:
  - `async function* multipartChunks(fieldName: string, filename: string, mimeType: string, chunks: AsyncIterable<Buffer>, boundary: string): AsyncIterable<Buffer>` — yields a correctly-framed `multipart/form-data` body.
  - `class GenericHTTPUploadProvider implements Provider`, constructor `new GenericHTTPUploadProvider(uploadUrl: string, fieldName = "file")`. `upload()` streams the multipart body to `uploadUrl` via `fetch` with a `ReadableStream` body (`duplex: "half"`), expecting a JSON response with an `"id"` field and optional `"expiresAt"`.

- [ ] **Step 1: Write the failing tests**

Create `typescript/test/providers/custom.test.ts`:

```typescript
import { describe, expect, it, vi } from "vitest";
import { GenericHTTPUploadProvider, multipartChunks } from "../../src/providers/custom.js";

async function* toAsyncIterable(chunks: Buffer[]): AsyncIterable<Buffer> {
  for (const chunk of chunks) yield chunk;
}

async function collect(it: AsyncIterable<Buffer>): Promise<Buffer> {
  const parts: Buffer[] = [];
  for await (const chunk of it) parts.push(chunk);
  return Buffer.concat(parts);
}

describe("multipartChunks", () => {
  it("produces a well-formed multipart body", async () => {
    const body = await collect(
      multipartChunks(
        "file",
        "photo.png",
        "image/png",
        toAsyncIterable([Buffer.from("AB"), Buffer.from("CD")]),
        "TESTBOUNDARY"
      )
    );

    expect(body.toString("latin1")).toContain("--TESTBOUNDARY\r\n");
    expect(body.toString("latin1")).toContain(
      'Content-Disposition: form-data; name="file"; filename="photo.png"'
    );
    expect(body.toString("latin1")).toContain("Content-Type: image/png");
    expect(body.toString("latin1")).toContain("ABCD");
    expect(body.toString("latin1")).toMatch(/--TESTBOUNDARY--\r\n$/);
  });
});

describe("GenericHTTPUploadProvider", () => {
  it("supports any media type", () => {
    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    expect(provider.supportsMediaType("application/x-whatever")).toBe(true);
  });

  it("posts the stream and parses the returned id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: "custom-ref-1", expiresAt: 999 }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    const ref = await provider.upload(toAsyncIterable([Buffer.from("AB")]), "image/png");

    expect(ref).toEqual({ id: "custom-ref-1", expiresAt: 999 });
    expect(fetchMock).toHaveBeenCalledWith(
      "https://example.com/upload",
      expect.objectContaining({ method: "POST" })
    );

    vi.unstubAllGlobals();
  });

  it("builds generic reference and inline blocks", () => {
    const provider = new GenericHTTPUploadProvider("https://example.com/upload");
    expect(provider.buildReferenceBlock({ id: "r1", expiresAt: null }, "image/png")).toEqual({
      type: "file_reference",
      id: "r1",
    });
    expect(provider.buildInlineBlock("AAAA", "image/png")).toEqual({
      type: "inline_base64",
      mimeType: "image/png",
      data: "AAAA",
    });
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd typescript && npx vitest run test/providers/custom.test.ts`
Expected: FAIL — cannot find module `../../src/providers/custom.js`

- [ ] **Step 3: Implement `providers/custom.ts`**

Create `typescript/src/providers/custom.ts`:

```typescript
import type { Provider, ProviderRef } from "./types.js";

export async function* multipartChunks(
  fieldName: string,
  filename: string,
  mimeType: string,
  chunks: AsyncIterable<Buffer>,
  boundary: string
): AsyncIterable<Buffer> {
  const preamble =
    `--${boundary}\r\n` +
    `Content-Disposition: form-data; name="${fieldName}"; filename="${filename}"\r\n` +
    `Content-Type: ${mimeType}\r\n\r\n`;
  yield Buffer.from(preamble, "utf-8");
  for await (const chunk of chunks) {
    yield chunk;
  }
  yield Buffer.from(`\r\n--${boundary}--\r\n`, "utf-8");
}

function toWebReadableStream(chunks: AsyncIterable<Buffer>): ReadableStream<Uint8Array> {
  const iterator = chunks[Symbol.asyncIterator]();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { value, done } = await iterator.next();
      if (done) {
        controller.close();
      } else {
        controller.enqueue(value);
      }
    },
  });
}

export class GenericHTTPUploadProvider implements Provider {
  constructor(private uploadUrl: string, private fieldName: string = "file") {}

  supportsMediaType(): boolean {
    return true;
  }

  inlineSizeLimit(): number {
    return 0;
  }

  async upload(chunks: AsyncIterable<Buffer>, mimeType: string): Promise<ProviderRef> {
    const boundary = "SiphonBoundary7f3a9c";
    const body = toWebReadableStream(multipartChunks(this.fieldName, "upload", mimeType, chunks, boundary));

    const response = await fetch(this.uploadUrl, {
      method: "POST",
      headers: { "Content-Type": `multipart/form-data; boundary=${boundary}` },
      body,
      duplex: "half",
    } as RequestInit & { duplex: "half" });

    if (!response.ok) {
      throw new Error(`Upload to ${this.uploadUrl} failed with status ${response.status}`);
    }
    const data = (await response.json()) as { id: string; expiresAt?: number };
    return { id: data.id, expiresAt: data.expiresAt ?? null };
  }

  buildReferenceBlock(ref: ProviderRef): Record<string, unknown> {
    return { type: "file_reference", id: ref.id };
  }

  buildInlineBlock(base64Data: string, mimeType: string): Record<string, unknown> {
    return { type: "inline_base64", mimeType, data: base64Data };
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd typescript && npx vitest run test/providers/custom.test.ts`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add typescript/src/providers/custom.ts typescript/test/providers/custom.test.ts
git commit -m "feat(typescript): add generic streaming multipart uploader for custom providers"
```

---

### Task 12: README and full-suite verification

**Files:**
- Create: `typescript/README.md`

- [ ] **Step 1: Write the README**

Create `typescript/README.md`:

```markdown
# Siphon (TypeScript)

Stream binary media (images, audio, video, PDFs) to multimodal LLM APIs
without paying Base64's 33% size penalty or buffering whole files in memory.

## Install

    npm install siphon openai @anthropic-ai/sdk @google/genai

Install only the peer packages for the providers you use.

## Usage

    import OpenAI from "openai";
    import { encodeMedia } from "siphon";

    const client = new OpenAI();
    const block = await encodeMedia(client, "openai", "photo.png");

    const response = await client.responses.create({
      model: "gpt-5",
      input: [{ role: "user", content: ["Describe this image.", block] }],
    });

Small files are inlined as Base64 automatically (default threshold: 256 KiB);
larger files are streamed to the provider's native file-upload API and
referenced by ID. Repeated uploads of identical content within the same
process reuse the cached reference instead of re-uploading.

## Custom providers

    import { registerProvider, encodeMedia } from "siphon";
    import { GenericHTTPUploadProvider } from "siphon/dist/providers/custom.js";

    registerProvider("my-server", new GenericHTTPUploadProvider("https://my-server/upload"));
    const block = await encodeMedia(null, "my-server", "clip.mp4");

## Known limitations (v1)

- The OpenAI, Anthropic, and Gemini adapters currently buffer the full
  payload into one `Buffer` before handing it to the SDK's upload call
  (their upload helpers expect a complete buffer/Blob, not an arbitrary
  async generator). True zero-buffering native upload is fully implemented
  for the **inline-fallback path** (streaming Base64) and for **custom
  providers** via `GenericHTTPUploadProvider`, which streams a real
  `ReadableStream` body over `fetch`.
- The upload cache is in-memory and per-process; it does not persist across
  restarts and is not shared across multiple processes.
- This package targets Node.js. Browser support (using `File`/`Blob`
  sources instead of `fs`-backed paths) would reuse the same `Provider`
  interface but needs its own `MediaSource` constructors — not built here.
```

- [ ] **Step 2: Run the full test suite**

Run: `cd typescript && npx vitest run`
Expected: all tests pass, no failures, no skips.

- [ ] **Step 3: Run the TypeScript compiler to check for type errors**

Run: `cd typescript && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add typescript/README.md
git commit -m "docs(typescript): add README with usage and known limitations"
```
