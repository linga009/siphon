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
