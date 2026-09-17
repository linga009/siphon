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
