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
