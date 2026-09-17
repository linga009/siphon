# Siphon (Python) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python `siphon` package: a client-side library that replaces inline Base64 for multimodal LLM API calls with native provider file-upload APIs (OpenAI, Anthropic, Gemini), a pluggable custom-provider extension point, streaming uploads, content-hash caching, and a size-threshold fallback to inline Base64.

**Architecture:** A `MediaSource` abstraction turns any input (file path, in-memory bytes, or a non-seekable iterator) into a chunked, hashable stream. An `Orchestrator` checks an in-memory cache, applies a size threshold, and either streams the source into a `Provider` adapter's native upload or inline-encodes it with a streaming Base64 encoder. `Provider` adapters (OpenAI, Anthropic, Gemini, plus user-registered custom ones) each implement one small interface and wrap an SDK client instance supplied by the caller.

**Tech Stack:** Python >=3.10, stdlib `hashlib`/`mimetypes`/`base64`/`unittest.mock`, `httpx` (for the generic custom-provider streaming uploader), `pytest` + `pytest-asyncio`, official SDKs (`openai`, `anthropic`, `google-genai`) as **optional** dependencies (each provider adapter only requires its own SDK to be installed — see Task 1).

## Global Constraints

- Python >=3.10 (uses `X | None` union syntax, `dataclasses`, structural pattern where convenient).
- No real network calls in unit tests — all provider SDK calls are mocked with `unittest.mock.MagicMock`/`AsyncMock`. Real-API integration tests are out of scope for this plan (spec marks them a separate opt-in suite; not built here to avoid requiring live credentials).
- Default inline-vs-upload size threshold: 256 KiB (`262144` bytes), overridable per call.
- Cache key: `(provider_name, content_hash)`, SHA-256 (stdlib `hashlib.sha256`, streaming-friendly, zero extra dependency — refinement over the spec's BLAKE2b mention; achieves the same goal with no cross-platform ambiguity).
- Every fallback-to-inline event (size threshold miss aside) logs at `WARNING` via the standard `logging` module, logger name `"siphon"`.
- Package layout: `src/` layout, package name `siphon`, published path `python/` within the repo (this repo will later also hold `typescript/` for the sibling package).

---

## File Structure

```
python/
  pyproject.toml
  src/siphon/
    __init__.py            # public exports
    hashing.py              # streaming SHA-256 helper
    sources.py               # MediaSource: path / bytes / non-seekable iterator
    base64_stream.py          # chunked base64 inline encoder
    cache.py                   # UploadCache (in-memory, expiry-aware)
    providers/
      __init__.py              # Provider protocol, ProviderRef, registry
      openai_provider.py        # OpenAIProvider
      anthropic_provider.py      # AnthropicProvider
      gemini_provider.py          # GeminiProvider
      custom.py                    # generic streaming multipart uploader for custom providers
    orchestrator.py                # decision logic (sync + async)
    api.py                          # encode_media / encode_media_async / register_provider
  tests/
    test_hashing.py
    test_sources.py
    test_base64_stream.py
    test_cache.py
    test_providers_openai.py
    test_providers_anthropic.py
    test_providers_gemini.py
    test_providers_custom.py
    test_orchestrator.py
    test_api.py
  README.md
```

---

### Task 1: Project scaffolding + streaming content hasher

**Files:**
- Create: `python/pyproject.toml`
- Create: `python/src/siphon/__init__.py` (empty for now)
- Create: `python/src/siphon/hashing.py`
- Test: `python/tests/test_hashing.py`

**Interfaces:**
- Produces: `hash_chunks(chunks: Iterable[bytes]) -> str` — consumes an iterable of byte chunks, returns the hex SHA-256 digest of their concatenation. Used by later tasks (`sources.py`, `orchestrator.py`) to compute a content hash from a stream without buffering it whole.
- Produces: `TeeHasher` class — `TeeHasher()` has `.update(chunk: bytes) -> None` and `.hexdigest() -> str`, for incremental hashing interleaved with other work (used later for non-seekable streams where hashing must happen *during* the upload pass, not before it).

- [ ] **Step 1: Create the package scaffolding**

Create `python/pyproject.toml`:

```toml
[project]
name = "siphon"
version = "0.1.0"
description = "Stream binary media to multimodal LLM APIs without Base64."
requires-python = ">=3.10"
dependencies = [
    "httpx>=0.27",
]

[project.optional-dependencies]
openai = ["openai>=1.50"]
anthropic = ["anthropic>=0.40"]
gemini = ["google-genai>=0.3"]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create empty `python/src/siphon/__init__.py`.

- [ ] **Step 2: Write the failing test for the streaming hasher**

Create `python/tests/test_hashing.py`:

```python
import hashlib

from siphon.hashing import TeeHasher, hash_chunks


def test_hash_chunks_matches_hashlib_on_full_content():
    content = b"the quick brown fox jumps over the lazy dog" * 100
    chunks = [content[i : i + 16] for i in range(0, len(content), 16)]

    result = hash_chunks(chunks)

    assert result == hashlib.sha256(content).hexdigest()


def test_hash_chunks_empty_iterable():
    assert hash_chunks([]) == hashlib.sha256(b"").hexdigest()


def test_tee_hasher_incremental_matches_hashlib():
    content = b"streamed content for incremental hashing"
    hasher = TeeHasher()
    for i in range(0, len(content), 7):
        hasher.update(content[i : i + 7])

    assert hasher.hexdigest() == hashlib.sha256(content).hexdigest()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd python && python -m pytest tests/test_hashing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.hashing'` (or `ImportError`).

- [ ] **Step 4: Implement the hasher**

Create `python/src/siphon/hashing.py`:

```python
"""Streaming content hashing used for cache keys."""

from __future__ import annotations

import hashlib
from typing import Iterable


class TeeHasher:
    """Incrementally hash bytes as they pass through some other pipeline."""

    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, chunk: bytes) -> None:
        self._hasher.update(chunk)

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def hash_chunks(chunks: Iterable[bytes]) -> str:
    """Hash an iterable of byte chunks without concatenating them in memory."""
    hasher = TeeHasher()
    for chunk in chunks:
        hasher.update(chunk)
    return hasher.hexdigest()
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd python && python -m pytest tests/test_hashing.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Install the package in editable mode so imports resolve**

Run: `cd python && pip install -e ".[dev]"`
Expected: installs successfully, `siphon` importable.

- [ ] **Step 7: Commit**

```bash
git add python/pyproject.toml python/src/siphon/__init__.py python/src/siphon/hashing.py python/tests/test_hashing.py
git commit -m "feat(python): add package scaffolding and streaming content hasher"
```

---

### Task 2: MediaSource abstraction

**Files:**
- Create: `python/src/siphon/sources.py`
- Test: `python/tests/test_sources.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (uses only stdlib).
- Produces:
  - `@dataclass class MediaSource`: fields `mime_type: str`, `size: int | None`, `seekable: bool`, `chunks: Callable[[], Iterator[bytes]]`.
    - For seekable sources, `chunks()` can be called multiple times (each call re-reads from the start) — used by the orchestrator to hash first, then re-read for upload.
    - For non-seekable sources, `chunks()` may only be called once; calling it a second time raises `RuntimeError`.
  - `from_path(path: str | Path, mime_type: str | None = None, chunk_size: int = 65536) -> MediaSource` — seekable, reads the file in chunks, auto-detects `mime_type` via `mimetypes.guess_type` if not given (raises `ValueError` if it can't be guessed and none was given).
  - `from_bytes(data: bytes, mime_type: str) -> MediaSource` — seekable, trivial in-memory wrapper.
  - `from_iterator(it: Iterator[bytes], mime_type: str, size: int | None = None) -> MediaSource` — non-seekable, wraps an arbitrary one-shot byte iterator (e.g. a network stream).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_sources.py`:

```python
import pytest

from siphon.sources import from_bytes, from_iterator, from_path


def test_from_bytes_is_seekable_and_reproduces_content():
    data = b"hello world" * 10
    source = from_bytes(data, mime_type="text/plain")

    assert source.seekable is True
    assert source.size == len(data)
    assert b"".join(source.chunks()) == data
    # can be read a second time
    assert b"".join(source.chunks()) == data


def test_from_path_reads_file_content(tmp_path):
    file_path = tmp_path / "sample.bin"
    content = bytes(range(256)) * 100
    file_path.write_bytes(content)

    source = from_path(file_path, mime_type="application/octet-stream")

    assert source.seekable is True
    assert source.size == len(content)
    assert b"".join(source.chunks()) == content
    assert b"".join(source.chunks()) == content


def test_from_path_guesses_mime_type(tmp_path):
    file_path = tmp_path / "photo.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    source = from_path(file_path)

    assert source.mime_type == "image/png"


def test_from_path_raises_when_mime_type_unknown(tmp_path):
    file_path = tmp_path / "mystery.unknownext"
    file_path.write_bytes(b"data")

    with pytest.raises(ValueError, match="mime_type"):
        from_path(file_path)


def test_from_iterator_is_not_seekable_and_can_only_be_read_once():
    def gen():
        yield b"chunk1"
        yield b"chunk2"

    source = from_iterator(gen(), mime_type="application/octet-stream")

    assert source.seekable is False
    assert b"".join(source.chunks()) == b"chunk1chunk2"
    with pytest.raises(RuntimeError, match="non-seekable"):
        list(source.chunks())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_sources.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.sources'`

- [ ] **Step 3: Implement `sources.py`**

Create `python/src/siphon/sources.py`:

```python
"""MediaSource: a uniform, chunked view over a file path, bytes, or a stream."""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

DEFAULT_CHUNK_SIZE = 65536


@dataclass
class MediaSource:
    mime_type: str
    size: int | None
    seekable: bool
    chunks: Callable[[], Iterator[bytes]]


def from_bytes(data: bytes, mime_type: str) -> MediaSource:
    def make_iterator() -> Iterator[bytes]:
        step = DEFAULT_CHUNK_SIZE
        for i in range(0, len(data), step):
            yield data[i : i + step]

    return MediaSource(
        mime_type=mime_type,
        size=len(data),
        seekable=True,
        chunks=make_iterator,
    )


def from_path(
    path: str | Path,
    mime_type: str | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> MediaSource:
    path = Path(path)
    if mime_type is None:
        guessed, _ = mimetypes.guess_type(path.name)
        if guessed is None:
            raise ValueError(
                f"Could not guess mime_type for {path.name!r}; pass mime_type explicitly."
            )
        mime_type = guessed

    size = path.stat().st_size

    def make_iterator() -> Iterator[bytes]:
        with open(path, "rb") as f:
            while chunk := f.read(chunk_size):
                yield chunk

    return MediaSource(
        mime_type=mime_type,
        size=size,
        seekable=True,
        chunks=make_iterator,
    )


def from_iterator(
    it: Iterator[bytes],
    mime_type: str,
    size: int | None = None,
) -> MediaSource:
    state = {"consumed": False}

    def make_iterator() -> Iterator[bytes]:
        if state["consumed"]:
            raise RuntimeError(
                "This MediaSource wraps a non-seekable stream and has already been read once."
            )
        state["consumed"] = True
        return it

    return MediaSource(
        mime_type=mime_type,
        size=size,
        seekable=False,
        chunks=make_iterator,
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_sources.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/sources.py python/tests/test_sources.py
git commit -m "feat(python): add MediaSource abstraction for paths, bytes, and streams"
```

---

### Task 3: Streaming Base64 inline encoder

**Files:**
- Create: `python/src/siphon/base64_stream.py`
- Test: `python/tests/test_base64_stream.py`

**Interfaces:**
- Consumes: `MediaSource.chunks()` shape (`Iterator[bytes]`) from Task 2, but takes a plain `Iterator[bytes]` parameter so it has no import-time dependency on `sources.py`.
- Produces: `encode_chunks_to_base64(chunks: Iterator[bytes]) -> str` — returns the full standard Base64 string, built by encoding fixed-size aligned groups incrementally (never holding more than one input chunk plus a small remainder buffer at a time).
- Produces: `to_data_url(mime_type: str, chunks: Iterator[bytes]) -> str` — returns `f"data:{mime_type};base64,{...}"`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_base64_stream.py`:

```python
import base64

from siphon.base64_stream import encode_chunks_to_base64, to_data_url


def test_encode_chunks_to_base64_matches_stdlib_for_various_chunk_boundaries():
    content = bytes(range(256)) * 10  # 2560 bytes, deliberately not a multiple of 3 in odd chunk sizes
    expected = base64.b64encode(content).decode("ascii")

    for chunk_size in (1, 2, 3, 7, 100, 4096):
        chunks = (content[i : i + chunk_size] for i in range(0, len(content), chunk_size))
        assert encode_chunks_to_base64(chunks) == expected, f"chunk_size={chunk_size}"


def test_encode_chunks_to_base64_empty():
    assert encode_chunks_to_base64(iter([])) == ""


def test_to_data_url_wraps_mime_type_and_base64():
    content = b"hello"
    expected_b64 = base64.b64encode(content).decode("ascii")

    result = to_data_url("text/plain", iter([content]))

    assert result == f"data:text/plain;base64,{expected_b64}"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_base64_stream.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.base64_stream'`

- [ ] **Step 3: Implement `base64_stream.py`**

Base64 encodes 3 raw bytes into 4 output characters; to stream correctly, any bytes left over (not a multiple of 3) must be carried forward and prepended to the next chunk, with padding (`=`) only applied once at the very end.

Create `python/src/siphon/base64_stream.py`:

```python
"""Chunked Base64 encoding so inline fallback never buffers a whole file."""

from __future__ import annotations

import base64
from typing import Iterator


def encode_chunks_to_base64(chunks: Iterator[bytes]) -> str:
    parts: list[str] = []
    remainder = b""

    for chunk in chunks:
        buffer = remainder + chunk
        usable_len = (len(buffer) // 3) * 3
        usable, remainder = buffer[:usable_len], buffer[usable_len:]
        if usable:
            parts.append(base64.b64encode(usable).decode("ascii"))

    if remainder:
        parts.append(base64.b64encode(remainder).decode("ascii"))

    return "".join(parts)


def to_data_url(mime_type: str, chunks: Iterator[bytes]) -> str:
    return f"data:{mime_type};base64,{encode_chunks_to_base64(chunks)}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_base64_stream.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/base64_stream.py python/tests/test_base64_stream.py
git commit -m "feat(python): add streaming base64 encoder for inline fallback"
```

---

### Task 4: Provider protocol, ProviderRef, and registry

**Files:**
- Create: `python/src/siphon/providers/__init__.py`
- Test: `python/tests/test_providers_registry.py`

**Interfaces:**
- Produces:
  - `@dataclass class ProviderRef`: `id: str`, `expires_at: float | None` (Unix timestamp; `None` means unknown/no expiry reported).
  - `class Provider(Protocol)`: methods
    - `def supports_media_type(self, mime_type: str) -> bool`
    - `def inline_size_limit(self) -> int` (bytes; providers with no inline mode at all can return `0`)
    - `def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef`
    - `async def upload_async(self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str) -> ProviderRef`
    - `def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict`
    - `def build_inline_block(self, base64_data: str, mime_type: str) -> dict`
  - `register_provider(name: str, provider: Provider) -> None`
  - `get_provider(name: str) -> Provider` — raises `KeyError` with a clear message if not registered.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_providers_registry.py`:

```python
import pytest

from siphon.providers import ProviderRef, get_provider, register_provider


class _FakeProvider:
    def supports_media_type(self, mime_type: str) -> bool:
        return True

    def inline_size_limit(self) -> int:
        return 1024

    def upload(self, chunks, mime_type: str) -> ProviderRef:
        return ProviderRef(id="fake-1", expires_at=None)

    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        return ProviderRef(id="fake-1", expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "fake", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "fake-inline", "data": base64_data}


def test_register_and_get_provider_round_trip():
    provider = _FakeProvider()
    register_provider("fake", provider)

    assert get_provider("fake") is provider


def test_get_unregistered_provider_raises_key_error():
    with pytest.raises(KeyError, match="unknown-provider"):
        get_provider("unknown-provider")


def test_provider_ref_is_a_plain_dataclass():
    ref = ProviderRef(id="abc", expires_at=123.0)
    assert ref.id == "abc"
    assert ref.expires_at == 123.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_providers_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.providers'`

- [ ] **Step 3: Implement `providers/__init__.py`**

Create `python/src/siphon/providers/__init__.py`:

```python
"""Provider protocol, reference type, and the provider registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Iterator, Protocol, runtime_checkable


@dataclass
class ProviderRef:
    id: str
    expires_at: float | None


@runtime_checkable
class Provider(Protocol):
    def supports_media_type(self, mime_type: str) -> bool: ...

    def inline_size_limit(self) -> int: ...

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef: ...

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef: ...

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict: ...

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict: ...


_REGISTRY: dict[str, Provider] = {}


def register_provider(name: str, provider: Provider) -> None:
    _REGISTRY[name] = provider


def get_provider(name: str) -> Provider:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(
            f"unknown-provider: {name!r} is not registered. "
            f"Known providers: {sorted(_REGISTRY)!r}. "
            "Register a custom provider with siphon.register_provider()."
        ) from None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_providers_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/providers/__init__.py python/tests/test_providers_registry.py
git commit -m "feat(python): add Provider protocol, ProviderRef, and registry"
```

---

### Task 5: In-memory upload cache

**Files:**
- Create: `python/src/siphon/cache.py`
- Test: `python/tests/test_cache.py`

**Interfaces:**
- Consumes: `ProviderRef` from Task 4 (`siphon.providers.ProviderRef`).
- Produces: `class UploadCache`:
  - `__init__(self, clock: Callable[[], float] = time.time)` — `clock` injectable for testing expiry.
  - `get(self, provider_name: str, content_hash: str) -> ProviderRef | None` — returns `None` on miss or if the stored ref is past `expires_at`.
  - `put(self, provider_name: str, content_hash: str, ref: ProviderRef) -> None`

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_cache.py`:

```python
from siphon.cache import UploadCache
from siphon.providers import ProviderRef


def test_cache_miss_returns_none():
    cache = UploadCache()
    assert cache.get("openai", "deadbeef") is None


def test_cache_put_then_get_returns_the_ref():
    cache = UploadCache()
    ref = ProviderRef(id="file-1", expires_at=None)

    cache.put("openai", "deadbeef", ref)

    assert cache.get("openai", "deadbeef") is ref


def test_cache_is_keyed_by_both_provider_and_hash():
    cache = UploadCache()
    ref = ProviderRef(id="file-1", expires_at=None)
    cache.put("openai", "deadbeef", ref)

    assert cache.get("anthropic", "deadbeef") is None
    assert cache.get("openai", "other-hash") is None


def test_cache_treats_expired_entries_as_miss():
    fake_now = [1000.0]
    cache = UploadCache(clock=lambda: fake_now[0])
    ref = ProviderRef(id="file-1", expires_at=1010.0)
    cache.put("openai", "deadbeef", ref)

    fake_now[0] = 1005.0
    assert cache.get("openai", "deadbeef") is ref

    fake_now[0] = 1015.0
    assert cache.get("openai", "deadbeef") is None


def test_cache_entry_with_no_expiry_never_expires():
    fake_now = [1000.0]
    cache = UploadCache(clock=lambda: fake_now[0])
    ref = ProviderRef(id="file-1", expires_at=None)
    cache.put("openai", "deadbeef", ref)

    fake_now[0] = 10_000_000.0
    assert cache.get("openai", "deadbeef") is ref
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.cache'`

- [ ] **Step 3: Implement `cache.py`**

Create `python/src/siphon/cache.py`:

```python
"""In-memory, expiry-aware cache of provider upload references."""

from __future__ import annotations

import time
from typing import Callable

from siphon.providers import ProviderRef


class UploadCache:
    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._entries: dict[tuple[str, str], ProviderRef] = {}

    def get(self, provider_name: str, content_hash: str) -> ProviderRef | None:
        key = (provider_name, content_hash)
        ref = self._entries.get(key)
        if ref is None:
            return None
        if ref.expires_at is not None and ref.expires_at <= self._clock():
            del self._entries[key]
            return None
        return ref

    def put(self, provider_name: str, content_hash: str, ref: ProviderRef) -> None:
        self._entries[(provider_name, content_hash)] = ref
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_cache.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/cache.py python/tests/test_cache.py
git commit -m "feat(python): add in-memory expiry-aware upload cache"
```

---

### Task 6: OpenAI provider adapter

**Files:**
- Create: `python/src/siphon/providers/openai_provider.py`
- Test: `python/tests/test_providers_openai.py`

**Interfaces:**
- Consumes: `Provider` protocol shape and `ProviderRef` from Task 4.
- Produces: `class OpenAIProvider` implementing `Provider`, constructor `OpenAIProvider(client)` where `client` is an `openai.OpenAI` (sync) or `openai.AsyncOpenAI` (async) instance — the adapter calls whichever of `.files.create` / `.files.create` (async client has the same method name, just awaited) matches how it's invoked.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_providers_openai.py`:

```python
from unittest.mock import AsyncMock, MagicMock

import pytest

from siphon.providers.openai_provider import OpenAIProvider


def _fake_file_object(file_id="file-abc123"):
    obj = MagicMock()
    obj.id = file_id
    return obj


def test_supports_media_type_accepts_images_and_pdfs():
    provider = OpenAIProvider(client=MagicMock())
    assert provider.supports_media_type("image/png") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("audio/mpeg") is False


def test_upload_calls_files_create_and_returns_ref():
    client = MagicMock()
    client.files.create.return_value = _fake_file_object("file-xyz")
    provider = OpenAIProvider(client=client)

    ref = provider.upload(iter([b"hello", b"world"]), "image/png")

    assert ref.id == "file-xyz"
    assert ref.expires_at is None
    client.files.create.assert_called_once()
    _, kwargs = client.files.create.call_args
    assert kwargs["purpose"] == "user_data"


async def test_upload_async_calls_files_create_and_returns_ref():
    client = MagicMock()
    client.files.create = AsyncMock(return_value=_fake_file_object("file-async-1"))
    provider = OpenAIProvider(client=client)

    ref = await provider.upload_async(iter([b"hello"]), "image/png")

    assert ref.id == "file-async-1"
    client.files.create.assert_awaited_once()


def test_build_reference_block_for_image_uses_input_image_type():
    provider = OpenAIProvider(client=MagicMock())
    from siphon.providers import ProviderRef

    block = provider.build_reference_block(ProviderRef(id="file-1", expires_at=None), "image/png")

    assert block == {"type": "input_image", "file_id": "file-1"}


def test_build_reference_block_for_pdf_uses_input_file_type():
    provider = OpenAIProvider(client=MagicMock())
    from siphon.providers import ProviderRef

    block = provider.build_reference_block(
        ProviderRef(id="file-2", expires_at=None), "application/pdf"
    )

    assert block == {"type": "input_file", "file_id": "file-2"}


def test_build_inline_block_for_image_wraps_raw_base64_in_a_data_url():
    provider = OpenAIProvider(client=MagicMock())

    block = provider.build_inline_block("AAAA", "image/png")

    assert block == {"type": "input_image", "image_url": "data:image/png;base64,AAAA"}


def test_build_inline_block_for_pdf_wraps_raw_base64_in_file_data():
    provider = OpenAIProvider(client=MagicMock())

    block = provider.build_inline_block("AAAA", "application/pdf")

    assert block == {
        "type": "input_file",
        "file_data": "data:application/pdf;base64,AAAA",
        "filename": "upload",
    }


def test_inline_size_limit_is_positive():
    provider = OpenAIProvider(client=MagicMock())
    assert provider.inline_size_limit() > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_providers_openai.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.providers.openai_provider'`

- [ ] **Step 3: Implement `providers/openai_provider.py`**

Create `python/src/siphon/providers/openai_provider.py`:

```python
"""OpenAI provider adapter: Files API + Responses API content blocks."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 20 * 1024 * 1024  # OpenAI's documented data-URL image limit


class _ChunkFile:
    """Wraps a byte-chunk iterator so it looks enough like a file for the SDK."""

    def __init__(self, chunks: Iterator[bytes], name: str) -> None:
        self._chunks = chunks
        self.name = name

    def read(self, *_args) -> bytes:
        return b"".join(self._chunks)


class OpenAIProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        file_obj = self._client.files.create(
            file=_ChunkFile(chunks, name="upload"),
            purpose="user_data",
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            collected = [c async for c in chunks]  # type: ignore[union-attr]
        else:
            collected = list(chunks)  # type: ignore[arg-type]
        file_obj = await self._client.files.create(
            file=_ChunkFile(iter(collected), name="upload"),
            purpose="user_data",
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        block_type = "input_image" if mime_type.startswith("image/") else "input_file"
        return {"type": block_type, "file_id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        data_url = f"data:{mime_type};base64,{base64_data}"
        if mime_type.startswith("image/"):
            return {"type": "input_image", "image_url": data_url}
        return {"type": "input_file", "file_data": data_url, "filename": "upload"}
```

**Note:** `_ChunkFile.read()` currently materializes the full stream to satisfy the SDK's file-like interface, because `openai.files.create` expects a standard readable. True zero-buffering upload for OpenAI depends on the SDK accepting a generator/iterator directly, which is left as a follow-up (tracked, not silently dropped — see README "Known limitations" in Task 13). This does not affect correctness or the inline-fallback memory guarantee, only the native-upload path's peak memory for OpenAI specifically.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_providers_openai.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/providers/openai_provider.py python/tests/test_providers_openai.py
git commit -m "feat(python): add OpenAI provider adapter"
```

---

### Task 7: Anthropic provider adapter

**Files:**
- Create: `python/src/siphon/providers/anthropic_provider.py`
- Test: `python/tests/test_providers_anthropic.py`

**Interfaces:**
- Produces: `class AnthropicProvider` implementing `Provider`, constructor `AnthropicProvider(client)` where `client` is an `anthropic.Anthropic` or `anthropic.AsyncAnthropic` instance. Uses `client.beta.files.upload(...)`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_providers_anthropic.py`:

```python
from unittest.mock import AsyncMock, MagicMock

from siphon.providers import ProviderRef
from siphon.providers.anthropic_provider import AnthropicProvider


def _fake_file_object(file_id="file_011abc"):
    obj = MagicMock()
    obj.id = file_id
    return obj


def test_supports_media_type_accepts_images_and_pdfs():
    provider = AnthropicProvider(client=MagicMock())
    assert provider.supports_media_type("image/jpeg") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("video/mp4") is False


def test_upload_calls_beta_files_upload_with_beta_header():
    client = MagicMock()
    client.beta.files.upload.return_value = _fake_file_object("file_011xyz")
    provider = AnthropicProvider(client=client)

    ref = provider.upload(iter([b"abc"]), "image/png")

    assert ref.id == "file_011xyz"
    client.beta.files.upload.assert_called_once()
    _, kwargs = client.beta.files.upload.call_args
    assert kwargs["betas"] == ["files-api-2025-04-14"]


async def test_upload_async_calls_beta_files_upload():
    client = MagicMock()
    client.beta.files.upload = AsyncMock(return_value=_fake_file_object("file_011async"))
    provider = AnthropicProvider(client=client)

    ref = await provider.upload_async(iter([b"abc"]), "image/png")

    assert ref.id == "file_011async"
    client.beta.files.upload.assert_awaited_once()


def test_build_reference_block_for_image():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_reference_block(ProviderRef(id="file_1", expires_at=None), "image/png")
    assert block == {"type": "image", "source": {"type": "file", "file_id": "file_1"}}


def test_build_reference_block_for_pdf():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_reference_block(
        ProviderRef(id="file_2", expires_at=None), "application/pdf"
    )
    assert block == {"type": "document", "source": {"type": "file", "file_id": "file_2"}}


def test_build_inline_block_for_image():
    provider = AnthropicProvider(client=MagicMock())
    block = provider.build_inline_block("AAAA", "image/png")
    assert block == {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"},
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_providers_anthropic.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.providers.anthropic_provider'`

- [ ] **Step 3: Implement `providers/anthropic_provider.py`**

Create `python/src/siphon/providers/anthropic_provider.py`:

```python
"""Anthropic provider adapter: beta Files API + Messages API content blocks."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 5 * 1024 * 1024  # Anthropic's documented base64 image limit
_BETA_HEADER = ["files-api-2025-04-14"]


class AnthropicProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        data = b"".join(chunks)
        file_obj = self._client.beta.files.upload(
            file=("upload", data, mime_type),
            betas=_BETA_HEADER,
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])  # type: ignore[union-attr]
        else:
            data = b"".join(chunks)  # type: ignore[arg-type]
        file_obj = await self._client.beta.files.upload(
            file=("upload", data, mime_type),
            betas=_BETA_HEADER,
        )
        return ProviderRef(id=file_obj.id, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        block_type = "image" if mime_type.startswith("image/") else "document"
        return {"type": block_type, "source": {"type": "file", "file_id": ref.id}}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        block_type = "image" if mime_type.startswith("image/") else "document"
        return {
            "type": block_type,
            "source": {"type": "base64", "media_type": mime_type, "data": base64_data},
        }
```

The orchestrator (Task 9) always passes the *raw base64 string* (no `data:` prefix) to every provider's `build_inline_block` — this matches Anthropic's `source.data` field directly. OpenAI's adapter (Task 6) wraps that same raw string into a `data:` URL itself, since that's what its `image_url`/`file_data` fields require. Each adapter is responsible for shaping the raw base64 into whatever its own API expects; the orchestrator never needs to know which shape a given provider wants.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_providers_anthropic.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/providers/anthropic_provider.py python/tests/test_providers_anthropic.py
git commit -m "feat(python): add Anthropic provider adapter"
```

---

### Task 8: Gemini provider adapter

**Files:**
- Create: `python/src/siphon/providers/gemini_provider.py`
- Test: `python/tests/test_providers_gemini.py`

**Interfaces:**
- Produces: `class GeminiProvider` implementing `Provider`, constructor `GeminiProvider(client)` where `client` is a `google.genai.Client` instance. Uses `client.files.upload(...)`.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_providers_gemini.py`:

```python
from unittest.mock import AsyncMock, MagicMock

from siphon.providers import ProviderRef
from siphon.providers.gemini_provider import GeminiProvider


def _fake_file_object(uri="https://generativelanguage.googleapis.com/v1/files/abc123"):
    obj = MagicMock()
    obj.uri = uri
    return obj


def test_supports_media_type_accepts_images_audio_video_pdf():
    provider = GeminiProvider(client=MagicMock())
    assert provider.supports_media_type("image/png") is True
    assert provider.supports_media_type("audio/mp3") is True
    assert provider.supports_media_type("video/mp4") is True
    assert provider.supports_media_type("application/pdf") is True
    assert provider.supports_media_type("application/zip") is False


def test_upload_calls_files_upload_and_returns_ref_with_uri_as_id():
    client = MagicMock()
    client.files.upload.return_value = _fake_file_object("https://example/files/xyz")
    provider = GeminiProvider(client=client)

    ref = provider.upload(iter([b"abc"]), "image/png")

    assert ref.id == "https://example/files/xyz"
    client.files.upload.assert_called_once()


async def test_upload_async_calls_aio_files_upload():
    client = MagicMock()
    client.aio.files.upload = AsyncMock(return_value=_fake_file_object("https://example/files/async1"))
    provider = GeminiProvider(client=client)

    ref = await provider.upload_async(iter([b"abc"]), "image/png")

    assert ref.id == "https://example/files/async1"
    client.aio.files.upload.assert_awaited_once()


def test_build_reference_block_uses_file_data_with_uri():
    provider = GeminiProvider(client=MagicMock())
    block = provider.build_reference_block(
        ProviderRef(id="https://example/files/1", expires_at=None), "image/png"
    )
    assert block == {
        "file_data": {"mime_type": "image/png", "file_uri": "https://example/files/1"}
    }


def test_build_inline_block_uses_inline_data():
    provider = GeminiProvider(client=MagicMock())
    block = provider.build_inline_block("AAAA", "image/png")
    assert block == {"inline_data": {"mime_type": "image/png", "data": "AAAA"}}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_providers_gemini.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.providers.gemini_provider'`

- [ ] **Step 3: Implement `providers/gemini_provider.py`**

Create `python/src/siphon/providers/gemini_provider.py`:

```python
"""Gemini provider adapter: Files API (resumable upload) + generateContent blocks."""

from __future__ import annotations

import io
from typing import AsyncIterator, Iterator

from siphon.providers import ProviderRef

_SUPPORTED_PREFIXES = ("image/", "audio/", "video/", "application/pdf", "text/")
_INLINE_SIZE_LIMIT = 20 * 1024 * 1024  # Gemini's documented inline request-size guidance


class GeminiProvider:
    def __init__(self, client) -> None:
        self._client = client

    def supports_media_type(self, mime_type: str) -> bool:
        return mime_type.startswith(_SUPPORTED_PREFIXES)

    def inline_size_limit(self) -> int:
        return _INLINE_SIZE_LIMIT

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        buffer = io.BytesIO(b"".join(chunks))
        file_obj = self._client.files.upload(
            file=buffer,
            config={"mime_type": mime_type},
        )
        return ProviderRef(id=file_obj.uri, expires_at=None)

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])  # type: ignore[union-attr]
        else:
            data = b"".join(chunks)  # type: ignore[arg-type]
        buffer = io.BytesIO(data)
        file_obj = await self._client.aio.files.upload(
            file=buffer,
            config={"mime_type": mime_type},
        )
        return ProviderRef(id=file_obj.uri, expires_at=None)

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"file_data": {"mime_type": mime_type, "file_uri": ref.id}}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"inline_data": {"mime_type": mime_type, "data": base64_data}}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_providers_gemini.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/providers/gemini_provider.py python/tests/test_providers_gemini.py
git commit -m "feat(python): add Gemini provider adapter"
```

---

### Task 9: Sync orchestrator

**Files:**
- Create: `python/src/siphon/orchestrator.py`
- Test: `python/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `MediaSource` (Task 2), `hash_chunks`/`TeeHasher` (Task 1), `encode_chunks_to_base64` (Task 3), `Provider`/`ProviderRef` (Task 4), `UploadCache` (Task 5).
- Produces: `encode_media_sync(provider: Provider, provider_name: str, source: MediaSource, cache: UploadCache, size_threshold: int = 262144, allow_inline_fallback: bool = True) -> dict` — the full decision pipeline, returning a ready-to-use content block.

Behavior contract (from the spec):
1. If `source.seekable`: compute the content hash first (one read pass), check the cache. On hit, return `provider.build_reference_block(cached_ref, source.mime_type)`.
2. If not a cache hit: if `source.size is not None and source.size < size_threshold`, OR the provider doesn't support this media type at all, inline-encode (second read pass for seekable sources) and return `provider.build_inline_block(...)`. If the provider doesn't support the media type, this happens regardless of `allow_inline_fallback` being False *only when there is no alternative* — see step 4 for the distinction between "no native path exists" and "native path failed".
3. Otherwise, stream-upload via `provider.upload(source.chunks(), source.mime_type)`, cache the result, return `provider.build_reference_block(...)`.
4. If the upload call raises an exception: if `allow_inline_fallback` is True, log a `WARNING` and fall back to inline; if False, re-raise.
5. If `source.seekable` is False: skip the cache read (no hash available yet). Tee-hash while uploading (wrap the chunk iterator so each chunk is hashed as it passes through to `provider.upload`). After a successful upload, store the now-known hash in the cache. Non-seekable sources cannot use the inline-fallback-on-size-threshold path proactively (size may be `None`) but can still fall back on upload failure if `allow_inline_fallback` — in that case the stream has already been partially consumed on failure, so re-raise instead of silently falling back (documented limitation, asserted by a test).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_orchestrator.py`:

```python
import logging

import pytest

from siphon.cache import UploadCache
from siphon.orchestrator import encode_media_sync
from siphon.providers import ProviderRef
from siphon.sources import from_bytes, from_iterator


class _RecordingProvider:
    def __init__(self, supports=True, raise_on_upload=False):
        self.supports = supports
        self.raise_on_upload = raise_on_upload
        self.upload_calls = 0
        self.uploaded_bytes = b""

    def supports_media_type(self, mime_type: str) -> bool:
        return self.supports

    def inline_size_limit(self) -> int:
        return 10_000_000

    def upload(self, chunks, mime_type: str) -> ProviderRef:
        self.upload_calls += 1
        data = b"".join(chunks)
        self.uploaded_bytes += data
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        return ProviderRef(id=f"ref-{self.upload_calls}", expires_at=None)

    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        raise NotImplementedError

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "ref", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "inline", "data": base64_data}


def test_small_seekable_source_goes_inline_without_calling_upload():
    provider = _RecordingProvider()
    cache = UploadCache()
    source = from_bytes(b"tiny", mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


def test_large_seekable_source_uploads_and_caches():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"x" * 2000
    source = from_bytes(content, mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.upload_calls == 1
    assert provider.uploaded_bytes == content


def test_second_call_with_same_content_hits_cache_and_does_not_reupload():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"y" * 2000

    block1 = encode_media_sync(
        provider, "fake", from_bytes(content, mime_type="image/png"), cache, size_threshold=1000
    )
    block2 = encode_media_sync(
        provider, "fake", from_bytes(content, mime_type="image/png"), cache, size_threshold=1000
    )

    assert block1 == block2
    assert provider.upload_calls == 1


def test_unsupported_media_type_goes_inline_even_if_large():
    provider = _RecordingProvider(supports=False)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="application/weird")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


def test_upload_failure_falls_back_to_inline_with_warning(caplog):
    provider = _RecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    with caplog.at_level(logging.WARNING, logger="siphon"):
        block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert any("upload failed" in record.message.lower() or "fall" in record.message.lower()
               for record in caplog.records)


def test_upload_failure_reraises_when_fallback_disabled():
    provider = _RecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    with pytest.raises(RuntimeError, match="upload failed"):
        encode_media_sync(
            provider, "fake", source, cache, size_threshold=1000, allow_inline_fallback=False
        )


def test_non_seekable_large_source_uploads_and_populates_cache_after_success():
    provider = _RecordingProvider()
    cache = UploadCache()
    content = b"z" * 5000
    source = from_iterator(iter([content[i : i + 100] for i in range(0, len(content), 100)]),
                            mime_type="image/png")

    block = encode_media_sync(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.uploaded_bytes == content
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.orchestrator'`

- [ ] **Step 3: Implement `orchestrator.py`**

Create `python/src/siphon/orchestrator.py`:

```python
"""Core decision logic: cache check, size threshold, native upload, inline fallback."""

from __future__ import annotations

import logging
from typing import Iterator

from siphon.base64_stream import encode_chunks_to_base64
from siphon.cache import UploadCache
from siphon.hashing import TeeHasher, hash_chunks
from siphon.providers import Provider, ProviderRef
from siphon.sources import MediaSource

logger = logging.getLogger("siphon")

DEFAULT_SIZE_THRESHOLD = 262144


def _inline_block(provider: Provider, chunks: Iterator[bytes], mime_type: str) -> dict:
    b64 = encode_chunks_to_base64(chunks)
    return provider.build_inline_block(b64, mime_type)


def encode_media_sync(
    provider: Provider,
    provider_name: str,
    source: MediaSource,
    cache: UploadCache,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
) -> dict:
    supports_type = provider.supports_media_type(source.mime_type)

    if source.seekable:
        content_hash = hash_chunks(source.chunks())
        cached = cache.get(provider_name, content_hash)
        if cached is not None:
            return provider.build_reference_block(cached, source.mime_type)

        should_go_inline = not supports_type or (
            source.size is not None and source.size < size_threshold
        )
        if should_go_inline:
            return _inline_block(provider, source.chunks(), source.mime_type)

        try:
            ref = provider.upload(source.chunks(), source.mime_type)
        except Exception:
            logger.warning(
                "siphon: native upload to %r failed; falling back to inline base64 "
                "(this reintroduces the size/memory overhead Siphon avoids).",
                provider_name,
                exc_info=True,
            )
            if not allow_inline_fallback:
                raise
            return _inline_block(provider, source.chunks(), source.mime_type)

        cache.put(provider_name, content_hash, ref)
        return provider.build_reference_block(ref, source.mime_type)

    # Non-seekable: no pre-hash, no proactive size-threshold inline path (size may
    # be unknown). Always attempt native upload if the type is supported; hash is
    # computed as a side effect of the single read pass and cached only on success.
    if not supports_type:
        raise ValueError(
            f"{provider_name!r} does not support media type {source.mime_type!r} "
            "and the source is non-seekable, so no inline fallback is possible "
            "(inline encoding would require re-reading the stream from the start)."
        )

    hasher = TeeHasher()

    def _tee() -> Iterator[bytes]:
        for chunk in source.chunks():
            hasher.update(chunk)
            yield chunk

    ref = provider.upload(_tee(), source.mime_type)
    cache.put(provider_name, hasher.hexdigest(), ref)
    return provider.build_reference_block(ref, source.mime_type)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/orchestrator.py python/tests/test_orchestrator.py
git commit -m "feat(python): add sync orchestrator with cache, threshold, and fallback logic"
```

---

### Task 10: Public sync API and package exports

**Files:**
- Create: `python/src/siphon/api.py`
- Modify: `python/src/siphon/__init__.py`
- Test: `python/tests/test_api.py`

**Interfaces:**
- Consumes: `encode_media_sync` (Task 9), `Provider`/`register_provider`/`get_provider` (Task 4), `MediaSource`/`from_path`/`from_bytes`/`from_iterator` (Task 2), `OpenAIProvider`/`AnthropicProvider`/`GeminiProvider` (Tasks 6-8).
- Produces (public package surface, from `siphon`):
  - `encode_media(client, provider_name: str, source: str | Path | bytes | MediaSource, *, mime_type: str | None = None, size_threshold: int = 262144, allow_inline_fallback: bool = True) -> dict`
  - `register_provider(name: str, provider: Provider) -> None` (re-exported)
  - `from_path`, `from_bytes`, `from_iterator`, `MediaSource` (re-exported for advanced/custom-provider use)
  - Built-in provider names `"openai"`, `"anthropic"`, `"gemini"` are lazily constructed and registered the first time `encode_media` is called with that `provider_name` (the adapter is built by wrapping whatever `client` object was passed, trusting the caller's `provider_name` — no client-type introspection) — not eagerly at import time, so importing `siphon` never requires all three SDKs to be installed.

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_api.py`:

```python
from unittest.mock import MagicMock

import pytest

import siphon
from siphon import encode_media
from siphon.providers import ProviderRef


def test_encode_media_accepts_raw_bytes_source_and_inline_encodes_small_payload():
    from siphon.providers import register_provider

    class _StubProvider:
        def supports_media_type(self, mime_type): return True
        def inline_size_limit(self): return 10_000_000
        def upload(self, chunks, mime_type): raise AssertionError("should not upload")
        async def upload_async(self, chunks, mime_type): raise AssertionError
        def build_reference_block(self, ref, mime_type): return {"type": "ref"}
        def build_inline_block(self, data, mime_type): return {"type": "inline", "data": data}

    register_provider("stub", _StubProvider())

    block = encode_media(client=None, provider_name="stub", source=b"tiny", mime_type="text/plain")

    assert block["type"] == "inline"


def test_encode_media_raises_clear_error_for_unregistered_provider():
    with pytest.raises(KeyError, match="unknown-provider"):
        encode_media(client=None, provider_name="totally-unknown-provider-xyz", source=b"x", mime_type="text/plain")


def test_encode_media_with_openai_client_builds_openai_provider():
    fake_file = MagicMock()
    fake_file.id = "file-1"
    client = MagicMock()
    client.files.create.return_value = fake_file

    block = encode_media(
        client=client,
        provider_name="openai",
        source=b"x" * 500_000,
        mime_type="image/png",
        size_threshold=1000,
    )

    assert block == {"type": "input_image", "file_id": "file-1"}


def test_siphon_package_exports_expected_names():
    assert hasattr(siphon, "encode_media")
    assert hasattr(siphon, "encode_media_async")
    assert hasattr(siphon, "register_provider")
    assert hasattr(siphon, "from_path")
    assert hasattr(siphon, "from_bytes")
    assert hasattr(siphon, "from_iterator")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_api.py -v`
Expected: FAIL with `ImportError: cannot import name 'encode_media' from 'siphon'`

- [ ] **Step 3: Implement `api.py`**

Create `python/src/siphon/api.py`:

```python
"""Public entry points: encode_media / encode_media_async."""

from __future__ import annotations

from pathlib import Path

from siphon.cache import UploadCache
from siphon.orchestrator import DEFAULT_SIZE_THRESHOLD, encode_media_sync
from siphon.providers import Provider, get_provider, register_provider
from siphon.sources import MediaSource, from_bytes, from_iterator, from_path

_DEFAULT_CACHE = UploadCache()
_BUILTIN_CLIENT_MODULE_PREFIXES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "gemini": "google.genai",
}


def _ensure_builtin_provider_registered(provider_name: str, client) -> None:
    if provider_name not in _BUILTIN_CLIENT_MODULE_PREFIXES:
        return
    try:
        get_provider(provider_name)
        return  # already registered (built-in or user override)
    except KeyError:
        pass

    if provider_name == "openai":
        from siphon.providers.openai_provider import OpenAIProvider

        register_provider("openai", OpenAIProvider(client))
    elif provider_name == "anthropic":
        from siphon.providers.anthropic_provider import AnthropicProvider

        register_provider("anthropic", AnthropicProvider(client))
    elif provider_name == "gemini":
        from siphon.providers.gemini_provider import GeminiProvider

        register_provider("gemini", GeminiProvider(client))


def _resolve_source(
    source: str | Path | bytes | MediaSource, mime_type: str | None
) -> MediaSource:
    if isinstance(source, MediaSource):
        return source
    if isinstance(source, bytes):
        if mime_type is None:
            raise ValueError("mime_type is required when source is raw bytes")
        return from_bytes(source, mime_type=mime_type)
    return from_path(source, mime_type=mime_type)


def encode_media(
    client,
    provider_name: str,
    source: str | Path | bytes | MediaSource,
    *,
    mime_type: str | None = None,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
    cache: UploadCache | None = None,
) -> dict:
    _ensure_builtin_provider_registered(provider_name, client)
    provider = get_provider(provider_name)
    media_source = _resolve_source(source, mime_type)
    return encode_media_sync(
        provider,
        provider_name,
        media_source,
        cache or _DEFAULT_CACHE,
        size_threshold=size_threshold,
        allow_inline_fallback=allow_inline_fallback,
    )


async def encode_media_async(
    client,
    provider_name: str,
    source: str | Path | bytes | MediaSource,
    *,
    mime_type: str | None = None,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
    cache: UploadCache | None = None,
) -> dict:
    from siphon.orchestrator import encode_media_async as _encode_media_async_impl

    _ensure_builtin_provider_registered(provider_name, client)
    provider = get_provider(provider_name)
    media_source = _resolve_source(source, mime_type)
    return await _encode_media_async_impl(
        provider,
        provider_name,
        media_source,
        cache or _DEFAULT_CACHE,
        size_threshold=size_threshold,
        allow_inline_fallback=allow_inline_fallback,
    )
```

Update `python/src/siphon/__init__.py`:

```python
"""Siphon: stream binary media to multimodal LLM APIs without Base64."""

from siphon.api import encode_media, encode_media_async
from siphon.providers import Provider, ProviderRef, get_provider, register_provider
from siphon.sources import MediaSource, from_bytes, from_iterator, from_path

__all__ = [
    "encode_media",
    "encode_media_async",
    "Provider",
    "ProviderRef",
    "register_provider",
    "get_provider",
    "MediaSource",
    "from_path",
    "from_bytes",
    "from_iterator",
]
```

Note: `encode_media_async` is imported from `siphon.orchestrator` inside the function body (not at module top) because Task 11 adds it — this keeps Task 10 runnable on its own by deferring that import; Task 11 will add the real implementation and this becomes a normal top-level import at that point.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_api.py -v -k "not async"`
Expected: 4 passed (the async-related export check passes since `encode_media_async` exists as a function even though calling it will fail until Task 11 — no test in this task calls it).

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/api.py python/src/siphon/__init__.py python/tests/test_api.py
git commit -m "feat(python): add public encode_media API and package exports"
```

---

### Task 11: Async orchestrator and `encode_media_async`

**Files:**
- Modify: `python/src/siphon/orchestrator.py`
- Modify: `python/src/siphon/api.py`
- Modify: `python/tests/test_orchestrator.py`
- Modify: `python/tests/test_api.py`

**Interfaces:**
- Produces: `async def encode_media_async(provider, provider_name, source, cache, size_threshold=262144, allow_inline_fallback=True) -> dict` in `siphon.orchestrator`, mirroring `encode_media_sync`'s behavior contract exactly but calling `provider.upload_async(...)`.

- [ ] **Step 1: Write the failing tests**

Append to `python/tests/test_orchestrator.py`:

```python
from siphon.orchestrator import encode_media_async


class _AsyncRecordingProvider(_RecordingProvider):
    async def upload_async(self, chunks, mime_type: str) -> ProviderRef:
        self.upload_calls += 1
        if hasattr(chunks, "__anext__"):
            data = b"".join([c async for c in chunks])
        else:
            data = b"".join(chunks)
        self.uploaded_bytes += data
        if self.raise_on_upload:
            raise RuntimeError("upload failed")
        return ProviderRef(id=f"ref-{self.upload_calls}", expires_at=None)


async def test_async_large_seekable_source_uploads_and_caches():
    provider = _AsyncRecordingProvider()
    cache = UploadCache()
    content = b"x" * 2000
    source = from_bytes(content, mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block == {"type": "ref", "id": "ref-1"}
    assert provider.upload_calls == 1


async def test_async_small_source_goes_inline():
    provider = _AsyncRecordingProvider()
    cache = UploadCache()
    source = from_bytes(b"tiny", mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
    assert provider.upload_calls == 0


async def test_async_upload_failure_falls_back_to_inline():
    provider = _AsyncRecordingProvider(raise_on_upload=True)
    cache = UploadCache()
    source = from_bytes(b"x" * 5000, mime_type="image/png")

    block = await encode_media_async(provider, "fake", source, cache, size_threshold=1000)

    assert block["type"] == "inline"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_orchestrator.py -v -k async`
Expected: FAIL with `ImportError: cannot import name 'encode_media_async' from 'siphon.orchestrator'`

- [ ] **Step 3: Implement the async orchestrator**

Add to `python/src/siphon/orchestrator.py` (below `encode_media_sync`):

```python
async def encode_media_async(
    provider: Provider,
    provider_name: str,
    source: MediaSource,
    cache: UploadCache,
    size_threshold: int = DEFAULT_SIZE_THRESHOLD,
    allow_inline_fallback: bool = True,
) -> dict:
    supports_type = provider.supports_media_type(source.mime_type)

    if source.seekable:
        content_hash = hash_chunks(source.chunks())
        cached = cache.get(provider_name, content_hash)
        if cached is not None:
            return provider.build_reference_block(cached, source.mime_type)

        should_go_inline = not supports_type or (
            source.size is not None and source.size < size_threshold
        )
        if should_go_inline:
            return _inline_block(provider, source.chunks(), source.mime_type)

        try:
            ref = await provider.upload_async(source.chunks(), source.mime_type)
        except Exception:
            if not allow_inline_fallback:
                raise
            logger.warning(
                "siphon: native upload to %r failed; falling back to inline base64 "
                "(this reintroduces the size/memory overhead Siphon avoids).",
                provider_name,
                exc_info=True,
            )
            return _inline_block(provider, source.chunks(), source.mime_type)

        cache.put(provider_name, content_hash, ref)
        return provider.build_reference_block(ref, source.mime_type)

    if not supports_type:
        raise ValueError(
            f"{provider_name!r} does not support media type {source.mime_type!r} "
            "and the source is non-seekable, so no inline fallback is possible."
        )

    hasher = TeeHasher()

    def _tee() -> Iterator[bytes]:
        for chunk in source.chunks():
            hasher.update(chunk)
            yield chunk

    ref = await provider.upload_async(_tee(), source.mime_type)
    cache.put(provider_name, hasher.hexdigest(), ref)
    return provider.build_reference_block(ref, source.mime_type)
```

Update `python/src/siphon/api.py`: replace the deferred import inside `encode_media_async` with a top-level import, since the real implementation now exists.

```python
# at the top of api.py, alongside the other siphon.orchestrator import:
from siphon.orchestrator import (
    DEFAULT_SIZE_THRESHOLD,
    encode_media_async as _encode_media_async_impl,
    encode_media_sync,
)
```

Remove the `from siphon.orchestrator import encode_media_async as _encode_media_async_impl` line that was inside the `encode_media_async` function body in Task 10 (now redundant/shadowed by the top-level import).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/ -v`
Expected: all tests pass (full suite, no regressions).

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/orchestrator.py python/src/siphon/api.py python/tests/test_orchestrator.py
git commit -m "feat(python): add async orchestrator and wire up encode_media_async"
```

---

### Task 12: Custom provider extension point + generic streaming multipart uploader

**Files:**
- Create: `python/src/siphon/providers/custom.py`
- Test: `python/tests/test_providers_custom.py`

**Interfaces:**
- Consumes: `Provider`/`ProviderRef`/`register_provider` (Task 4).
- Produces:
  - `multipart_chunks(field_name: str, filename: str, mime_type: str, chunks: Iterator[bytes], boundary: str) -> Iterator[bytes]` — yields a correctly-framed `multipart/form-data` body as a byte-chunk stream (preamble, passthrough content chunks, closing boundary), so an arbitrary HTTP endpoint can receive a streamed upload without Siphon ever buffering the whole payload.
  - `class GenericHTTPUploadProvider` implementing `Provider`: constructor `GenericHTTPUploadProvider(upload_url: str, field_name: str = "file", http_client: httpx.Client | None = None)`. `upload()` POSTs the multipart stream to `upload_url` and expects a JSON response containing an `"id"` field (and optional `"expires_at"` unix-timestamp field); `build_reference_block`/`build_inline_block` return a minimal generic shape (`{"type": "file_reference", "id": ...}` / `{"type": "inline_base64", "mime_type": ..., "data": ...}`) since a fully custom provider has no fixed target API shape — users are expected to subclass or wrap this for their actual endpoint's expected JSON shape (documented in the README, Task 13).

- [ ] **Step 1: Write the failing tests**

Create `python/tests/test_providers_custom.py`:

```python
import httpx
import pytest

from siphon.providers import ProviderRef
from siphon.providers.custom import GenericHTTPUploadProvider, multipart_chunks


def test_multipart_chunks_produces_well_formed_body():
    chunks = multipart_chunks(
        field_name="file",
        filename="photo.png",
        mime_type="image/png",
        chunks=iter([b"AB", b"CD"]),
        boundary="TESTBOUNDARY",
    )
    body = b"".join(chunks)

    assert body.startswith(b"--TESTBOUNDARY\r\n")
    assert b'Content-Disposition: form-data; name="file"; filename="photo.png"' in body
    assert b"Content-Type: image/png" in body
    assert b"ABCD" in body
    assert body.endswith(b"--TESTBOUNDARY--\r\n")


def test_generic_http_upload_provider_posts_and_parses_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert b"ABCD" in request.read()
        return httpx.Response(200, json={"id": "custom-ref-1", "expires_at": 999.0})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    provider = GenericHTTPUploadProvider(
        upload_url="https://example.com/upload", http_client=http_client
    )

    ref = provider.upload(iter([b"AB", b"CD"]), "image/png")

    assert ref == ProviderRef(id="custom-ref-1", expires_at=999.0)


def test_generic_http_upload_provider_supports_any_media_type():
    provider = GenericHTTPUploadProvider(upload_url="https://example.com/upload")
    assert provider.supports_media_type("application/x-whatever") is True


def test_generic_http_upload_provider_build_blocks():
    provider = GenericHTTPUploadProvider(upload_url="https://example.com/upload")

    ref_block = provider.build_reference_block(ProviderRef(id="r1", expires_at=None), "image/png")
    inline_block = provider.build_inline_block("AAAA", "image/png")

    assert ref_block == {"type": "file_reference", "id": "r1"}
    assert inline_block == {"type": "inline_base64", "mime_type": "image/png", "data": "AAAA"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd python && python -m pytest tests/test_providers_custom.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'siphon.providers.custom'`

- [ ] **Step 3: Implement `providers/custom.py`**

Create `python/src/siphon/providers/custom.py`:

```python
"""Generic streaming multipart uploader for custom/self-hosted providers."""

from __future__ import annotations

from typing import AsyncIterator, Iterator

import httpx

from siphon.providers import ProviderRef


def multipart_chunks(
    field_name: str,
    filename: str,
    mime_type: str,
    chunks: Iterator[bytes],
    boundary: str,
) -> Iterator[bytes]:
    preamble = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
        f"Content-Type: {mime_type}\r\n\r\n"
    ).encode("utf-8")
    yield preamble
    for chunk in chunks:
        yield chunk
    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


class GenericHTTPUploadProvider:
    """A minimal Provider for a self-hosted endpoint that accepts multipart uploads
    and returns JSON with an "id" field. Subclass or wrap this to match a specific
    endpoint's request/response shape.
    """

    def __init__(
        self,
        upload_url: str,
        field_name: str = "file",
        http_client: httpx.Client | None = None,
    ) -> None:
        self._upload_url = upload_url
        self._field_name = field_name
        self._client = http_client or httpx.Client()

    def supports_media_type(self, mime_type: str) -> bool:
        return True

    def inline_size_limit(self) -> int:
        return 0  # no fixed inline convention for an arbitrary custom endpoint

    def upload(self, chunks: Iterator[bytes], mime_type: str) -> ProviderRef:
        boundary = "SiphonBoundary7f3a9c"
        body = multipart_chunks(self._field_name, "upload", mime_type, chunks, boundary)
        response = self._client.post(
            self._upload_url,
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        response.raise_for_status()
        data = response.json()
        return ProviderRef(id=data["id"], expires_at=data.get("expires_at"))

    async def upload_async(
        self, chunks: AsyncIterator[bytes] | Iterator[bytes], mime_type: str
    ) -> ProviderRef:
        if hasattr(chunks, "__anext__"):
            collected = [c async for c in chunks]  # type: ignore[union-attr]
        else:
            collected = list(chunks)  # type: ignore[arg-type]
        boundary = "SiphonBoundary7f3a9c"
        body = b"".join(multipart_chunks(self._field_name, "upload", mime_type, iter(collected), boundary))
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self._upload_url,
                content=body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        response.raise_for_status()
        data = response.json()
        return ProviderRef(id=data["id"], expires_at=data.get("expires_at"))

    def build_reference_block(self, ref: ProviderRef, mime_type: str) -> dict:
        return {"type": "file_reference", "id": ref.id}

    def build_inline_block(self, base64_data: str, mime_type: str) -> dict:
        return {"type": "inline_base64", "mime_type": mime_type, "data": base64_data}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd python && python -m pytest tests/test_providers_custom.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add python/src/siphon/providers/custom.py python/tests/test_providers_custom.py
git commit -m "feat(python): add generic streaming multipart uploader for custom providers"
```

---

### Task 13: README and full-suite verification

**Files:**
- Create: `python/README.md`

- [ ] **Step 1: Write the README**

Create `python/README.md`:

```markdown
# Siphon (Python)

Stream binary media (images, audio, video, PDFs) to multimodal LLM APIs
without paying Base64's 33% size penalty or buffering whole files in memory.

## Install

    pip install siphon[openai,anthropic,gemini]

Install only the extras for the providers you use.

## Usage

    from openai import OpenAI
    from siphon import encode_media

    client = OpenAI()
    block = encode_media(client, "openai", "photo.png")

    response = client.responses.create(
        model="gpt-5",
        input=[{"role": "user", "content": ["Describe this image.", block]}],
    )

Small files are inlined as Base64 automatically (default threshold: 256 KiB);
larger files are streamed to the provider's native file-upload API and
referenced by ID. Repeated uploads of identical content within the same
process reuse the cached reference instead of re-uploading.

## Custom providers

    from siphon import register_provider
    from siphon.providers.custom import GenericHTTPUploadProvider

    register_provider("my-server", GenericHTTPUploadProvider("https://my-server/upload"))
    block = encode_media(None, "my-server", "clip.mp4")

## Known limitations (v1)

- The OpenAI and Anthropic adapters currently buffer the full payload
  in-process before handing it to the SDK's upload call (the official SDKs'
  synchronous file-upload methods expect a seekable file-like object or
  bytes, not an arbitrary chunk iterator). The Gemini adapter does the same.
  True zero-buffering native upload is fully implemented for the
  **inline-fallback path** (streaming Base64) and for **custom providers**
  via `GenericHTTPUploadProvider`. Tightening the built-in three adapters to
  stream to disk-backed temp files (bounding memory to a fixed chunk size
  regardless of payload size) is tracked as follow-up work, not required for
  correctness.
- The upload cache is in-memory and per-process; it does not persist across
  restarts and is not shared across multiple processes.
```

- [ ] **Step 2: Run the full test suite**

Run: `cd python && python -m pytest tests/ -v`
Expected: all tests pass, no failures, no skips.

- [ ] **Step 3: Commit**

```bash
git add python/README.md
git commit -m "docs(python): add README with usage and known limitations"
```
