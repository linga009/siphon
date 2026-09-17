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
