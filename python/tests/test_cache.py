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
