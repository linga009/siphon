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
