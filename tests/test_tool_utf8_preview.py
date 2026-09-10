"""UTF-8 preview boundaries preserve complete characters without accepting invalid text."""

import pytest

from famou.tools import LocalToolRegistry

TRUNCATED = "\n[tool output truncated]"
CHARACTERS = ("¢", "中", "😀")


def read_preview(tmp_path, content: bytes, limit: int):
    path = tmp_path / "input.txt"
    path.write_bytes(content)
    return LocalToolRegistry(max_output_bytes=limit).execute(
        "read_file", {"path": path.name}, tmp_path,
    )


@pytest.mark.parametrize("character,retained_bytes", [
    (character, retained) for character in CHARACTERS
    for retained in range(len(character.encode("utf-8")) + 1)
])
def test_preview_at_every_multibyte_character_boundary(tmp_path, character, retained_bytes):
    prefix = "Aé"
    content = (prefix + character + "tail").encode("utf-8")
    limit = len(prefix.encode("utf-8")) + retained_bytes
    result = read_preview(tmp_path, content, limit)

    expected = prefix + (character if retained_bytes == len(character.encode("utf-8")) else "")
    assert result.success
    assert result.output == expected + TRUNCATED
    assert "\ufffd" not in result.output
    assert len(expected.encode("utf-8")) <= limit
    assert content.startswith(expected.encode("utf-8"))


@pytest.mark.parametrize("limit", [1, 2, 3])
def test_preview_smaller_than_first_character_returns_only_truncation_marker(tmp_path, limit):
    result = read_preview(tmp_path, "😀tail".encode(), limit)
    assert result.success and result.output == TRUNCATED


@pytest.mark.parametrize("text", ["", "ascii", "¢", "中", "😀", "A¢中😀"])
def test_complete_file_at_or_below_limit_is_strict_and_not_marked_truncated(tmp_path, text):
    raw = text.encode("utf-8")
    result = read_preview(tmp_path, raw, max(1, len(raw)))
    assert result.success and result.output == text


@pytest.mark.parametrize("invalid", [
    b"\xff", b"\x80", b"\xc0\xaf", b"\xe0\x80\x80", b"\xed\xa0\x80",
    b"\xf4\x90\x80\x80", b"\xe4A",
])
def test_invalid_utf8_inside_truncated_prefix_still_fails(tmp_path, invalid):
    prefix = b"ok" + invalid
    result = read_preview(tmp_path, prefix + b"tail", len(prefix))
    assert not result.success
    assert "file is not valid UTF-8 text" in result.output


@pytest.mark.parametrize("character,retained_bytes", [
    (character, retained) for character in CHARACTERS
    for retained in range(1, len(character.encode("utf-8")))
])
@pytest.mark.parametrize("extra_capacity", [0, 5])
def test_incomplete_character_at_true_eof_still_fails(tmp_path, character, retained_bytes, extra_capacity):
    raw = b"ok" + character.encode("utf-8")[:retained_bytes]
    result = read_preview(tmp_path, raw, len(raw) + extra_capacity)
    assert not result.success
    assert "file is not valid UTF-8 text" in result.output


@pytest.mark.parametrize("limit,expected", [
    (1, "a" + TRUNCATED), (4, "abcd" + TRUNCATED), (5, "abcde"), (20, "abcde"),
])
def test_ascii_preview_limit_and_existing_suffix_are_preserved(tmp_path, limit, expected):
    result = read_preview(tmp_path, b"abcde", limit)
    assert result.success and result.output == expected


def test_default_preview_reproduces_observed_twenty_thousand_byte_cutoff(tmp_path):
    prefix = "a" * 19998
    raw = prefix.encode() + "中".encode() + b"b" * 8877
    assert len(raw) == 28878
    raw.decode("utf-8")
    with pytest.raises(UnicodeDecodeError):
        raw[:20000].decode("utf-8")
    (tmp_path / "input.csv").write_bytes(raw)
    registry = LocalToolRegistry()
    assert registry.max_output_bytes == 20000
    result = registry.execute("read_file", {"path": "input.csv"}, tmp_path)
    assert result.success and result.output == prefix + TRUNCATED
