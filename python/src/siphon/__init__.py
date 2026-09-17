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
