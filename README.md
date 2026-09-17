# Siphon

[![CI (Python)](https://github.com/linga009/siphon/actions/workflows/ci-python.yml/badge.svg)](https://github.com/linga009/siphon/actions/workflows/ci-python.yml)
[![CI (TypeScript)](https://github.com/linga009/siphon/actions/workflows/ci-typescript.yml/badge.svg)](https://github.com/linga009/siphon/actions/workflows/ci-typescript.yml)

**Stop Base64-encoding media into JSON. Stream it instead.**

Siphon is a client library — implemented independently in **Python** and
**TypeScript** — that replaces the "read the whole file, Base64-encode it,
stuff it into a JSON string" pattern most multimodal LLM integrations use
today. Instead, it streams binary media (images, audio, video, PDFs) to each
provider's native file-upload API and only falls back to inline Base64 when
that's actually the cheaper option.

```python
from openai import OpenAI
from siphon import encode_media

client = OpenAI()
block = encode_media(client, "openai", "photo.png")

response = client.responses.create(
    model="gpt-5",
    input=[{"role": "user", "content": ["Describe this image.", block]}],
)
```

```typescript
import OpenAI from "openai";
import { encodeMedia } from "siphon";

const client = new OpenAI();
const block = await encodeMedia(client, "openai", "photo.png");

const response = await client.responses.create({
  model: "gpt-5",
  input: [{ role: "user", content: ["Describe this image.", block] }],
});
```

## Why

Base64 was designed in the 1980s to push binary data through 7-bit ASCII
email systems. Used as the default way to get an image into a JSON API call,
it costs you three things at once:

- **A ~33% size penalty** on every request, every time.
- **Full in-memory buffering** — the whole file has to be read and
  re-encoded into a string before a single byte reaches the network.
- **No resumability.** If a large upload fails at 98%, you start over.

All three major hosted multimodal APIs (OpenAI, Anthropic, Gemini) already
offer a real alternative: upload the file once to a native Files API, then
reference it by ID in your request. But each provider's upload flow is
shaped differently, none of them make Base64 disappear entirely (small
files, unsupported endpoints, or providers with no Files API still need it),
and nothing unifies "pick the cheapest path, stream the bytes, cache the
result" behind one call — until now.

## How it works

Siphon wraps the official provider SDKs — it doesn't reimplement their
transport, auth, or retry logic. For each `encode_media` / `encodeMedia`
call, it:

1. **Hashes the content** and checks an in-memory cache — send the same file
   twice in one process, and the second call reuses the first upload instead
   of re-sending it.
2. **Decides inline vs. native upload** based on a configurable size
   threshold (256 KiB by default) and whether the provider supports the
   media type at all.
3. **Streams to the provider's native upload API** — OpenAI's Files API
   (via the Responses API), Anthropic's beta Files API, or Google Gemini's
   Files API — and returns a ready-to-use content block referencing the
   uploaded file by ID.
4. **Falls back to a streaming Base64 encoder** for small payloads or
   unsupported cases, with the fallback logged so it's never a silent cost
   regression.

A small `Provider` interface means you're not limited to the three built-in
adapters — register your own for a self-hosted model, a proxy, or any
OpenAI-compatible endpoint via the bundled `GenericHTTPUploadProvider`,
which streams a real multipart body instead of buffering it.

## Packages

| | Install | Docs |
|---|---|---|
| **Python** | `pip install siphon[openai,anthropic,gemini]` | [`python/README.md`](python/README.md) |
| **TypeScript** | `npm install siphon openai @anthropic-ai/sdk @google/genai` | [`typescript/README.md`](typescript/README.md) |

The two packages are separate, idiomatic implementations of the same
design — not a shared core compiled to both languages — so each reads
naturally in its own ecosystem (Python ships matching sync and async APIs,
mirroring the official provider SDKs' own `Client`/`AsyncClient` split;
TypeScript exposes a single `async` API, since Node has no meaningful
synchronous I/O story to mirror).

## Project layout

```
python/          Python package (src/ layout, pytest)
typescript/       TypeScript package (Node.js, vitest)
docs/superpowers/
  specs/           Design spec
  plans/           Implementation plans (one per package)
```

Both packages were built from the same [design spec](docs/superpowers/specs/2026-09-17-siphon-design.md)
via separate, fully-specified [implementation plans](docs/superpowers/plans/),
each executed task-by-task with an independent test-driven build and code
review per task, plus a final cross-package review before merge.

## Status

This is **Stage 1**: a client-side library that works against the real,
public APIs of OpenAI, Anthropic, and Gemini today. See each package's
README for current known limitations (the built-in provider adapters still
buffer the full payload in-process before upload — the SDK calls they wrap
require a complete buffer, not an arbitrary stream — while the
inline-fallback path and custom providers are fully streaming).

**Stage 2** — a new binary wire protocol for cases where you control both
the client and the server (a self-hosted model, or your own gateway in
front of a hosted API) — is a deliberately separate, not-yet-started
follow-up; it isn't part of this repository yet.

## CI/CD

Each package has its own GitHub Actions workflows, triggered independently
so a change to one package doesn't run the other's pipeline:

- **CI** ([`ci-python.yml`](.github/workflows/ci-python.yml),
  [`ci-typescript.yml`](.github/workflows/ci-typescript.yml)) — runs on every
  push and pull request that touches the corresponding package. Python is
  tested on 3.10/3.11/3.12; TypeScript is typechecked (both `src` and `test`)
  and tested on Node 18/20/22, then built.
- **Publish** ([`publish-python.yml`](.github/workflows/publish-python.yml),
  [`publish-typescript.yml`](.github/workflows/publish-typescript.yml)) —
  runs the full test suite again, then publishes to PyPI / npm, triggered by
  pushing a tag: `python-v0.1.0` or `typescript-v0.1.0`. Requires repo
  secrets `PYPI_API_TOKEN` and `NPM_TOKEN` (Settings → Secrets and
  variables → Actions) before the first tagged release — neither package
  has been published yet, so these aren't configured out of the box.

## License

[PolyForm Shield License 1.0.0](LICENSE.md) — free to use, modify, and
distribute for any purpose *except* providing a product or service that
competes with Siphon itself. If your use case falls under that exception,
reach out about a commercial license.
