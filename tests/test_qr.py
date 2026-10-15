"""The QR encoder (byte mode, error correction M, versions 1-10). The Reed-Solomon step is checked against the standard
worked example; the matrix's fixed patterns and format bits are checked directly. A development check decodes real
pairing links with macOS CoreImage."""
import pytest

from odie import qr


def test_reed_solomon_matches_the_worked_example():
    # "HELLO WORLD" at 1-M (alphanumeric data codewords), and its ten error correction codewords
    data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17]
    assert qr.rs_remainder(data, qr.rs_divisor(10)) == [196, 35, 39, 119, 235, 215, 231, 226, 93, 23]


def _format(m) -> int:
    size = len(m)
    bits = [m[i][8] for i in range(6)] + [m[7][8], m[8][8], m[8][7]] + [m[8][14 - i] for i in range(9, 15)]
    value = sum(1 << i for i, b in enumerate(bits) if b) ^ 0x5412
    other = [m[8][size - 1 - i] for i in range(8)] + [m[size - 15 + i][8] for i in range(8, 15)]
    assert sum(1 << i for i, b in enumerate(other) if b) ^ 0x5412 == value  # both copies agree
    return value


def test_matrix_structure():
    m = qr.encode("https://odie.local/pair?code=ABCD1234")
    size = len(m)
    assert size in (4 * v + 17 for v in range(1, 11)) and all(len(row) == size for row in m)
    for ox, oy in ((0, 0), (size - 7, 0), (0, size - 7)):  # the three finder patterns
        assert all(m[oy][ox + i] for i in range(7)) and all(m[oy + 6][ox + i] for i in range(7))
        assert m[oy + 1][ox] and not any(m[oy + 1][ox + i] for i in range(1, 6)) and m[oy + 1][ox + 6]
        assert all(m[oy + 3][ox + i] for i in (0, 2, 3, 4, 6)) and not m[oy + 3][ox + 1] and not m[oy + 3][ox + 5]
    assert [m[6][x] for x in range(8, size - 8)] == [x % 2 == 0 for x in range(8, size - 8)]  # timing
    assert m[size - 8][8] is True  # the dark module
    f = _format(m)
    assert f >> 13 == 0b00 and 0 <= (f >> 10) & 0b111 <= 7  # error correction M, a mask 0-7


def test_version_grows_with_length():
    assert len(qr.encode("x" * 10)) == 21
    assert len(qr.encode("x" * 60)) in (33, 37)
    assert qr.version_for(b"x" * 14) == 1 and qr.version_for(b"x" * 15) == 2


def test_too_long_is_refused():
    with pytest.raises(ValueError):
        qr.encode("x" * 400)


def test_svg_draws_the_dark_modules():
    s = qr.svg(qr.encode("hello"), scale=4, border=2)
    assert s.startswith("<svg") and 'viewBox="0 0 ' in s and s.count("h1v1h-1z") > 100
