"""The pairing QR code: the encoder's structure and error correction, and, where the reference library ``segno`` is
installed (a development check, not a dependency), module for module against it.

``segno`` writes one extra zero byte after the terminator when the data ends on a byte boundary; both are valid
(a reader stops at the terminator), so the cross-check places segno's own codewords with this encoder's function
patterns, masks and format bits and compares the whole matrix.
"""

from __future__ import annotations

import hashlib

import pytest

from octryx_claude import qr

URL = "https://octryx-eu-central-1.nonprod-cluster.cloud.example.com/m/pair#c=Q2xhdWRlLWZvci1PY3RyeXg"


def test_reed_solomon_matches_the_reference_vector():
    # Version 1-M data codewords of "A" (as segno pads them) and the 10 error correction codewords segno computes.
    data = [64, 20, 16, 0, 236, 17, 236, 17, 236, 17, 236, 17, 236, 17, 236, 17]
    assert qr._rs_remainder(data, qr._rs_divisor(10)) == [201, 132, 3, 176, 17, 3, 176, 205, 9, 220]


@pytest.mark.parametrize(("text", "version"), [("A", 1), ("x" * 20, 2), ("x" * 100, 6), (URL, 6), ("x" * 300, 13)])
def test_the_smallest_version_that_fits_is_used(text, version):
    rows = qr.encode(text)
    assert len(rows) == version * 4 + 17 and all(len(row) == len(rows) for row in rows)


def test_finder_timing_and_format_are_in_place():
    rows = qr.encode(URL, mask=3)
    size = len(rows)
    for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
        assert rows[cy][cx] and not rows[cy - 2][cx] and rows[cy - 3][cx]  # dark centre, light ring, dark ring
    assert [rows[6][x] for x in range(8, size - 8)] == [x % 2 == 0 for x in range(8, size - 8)]
    assert rows[size - 8][8]  # the dark module
    # Format bits (level M, mask 3) read back from around the top-left finder.
    bits = [rows[i][8] for i in range(6)] + [rows[7][8], rows[8][8], rows[8][7]]
    bits += [rows[8][14 - i] for i in range(9, 15)]
    value = sum(int(bit) << i for i, bit in enumerate(bits)) ^ 0x5412
    assert value >> 10 == (0 << 3 | 3)


def test_the_pairing_url_encodes_stably():
    rows = qr.encode(URL, mask=2)
    digest = hashlib.sha256("".join("1" if dark else "0" for row in rows for dark in row).encode()).hexdigest()
    assert digest == GOLDEN_URL_MASK2


def test_too_long_is_refused():
    with pytest.raises(qr.QrTooLongError):
        qr.encode("x" * 1000)


def test_terminal_lines_draw_light_modules_with_a_quiet_zone():
    rows = qr.encode("A")
    lines = qr.terminal_lines(rows, quiet=4)
    assert len(lines) == (21 + 8 + 1) // 2 and all(len(line) == 29 for line in lines)
    assert set(lines[0]) == {"█"}  # the quiet zone is light


def test_matches_segno_module_for_module():
    segno = pytest.importorskip("segno")
    for text in ("A", "hello world", "x" * 77, URL, "y" * 230):
        version = (len(qr.encode(text)) - 17) // 4
        for mask in range(8):
            reference = [[bool(v) for v in row] for row in segno.make(
                text, error="m", mode="byte", version=version, mask=mask, boost_error=False, micro=False).matrix]
            matrix = qr._Matrix(version)
            matrix.draw_function_patterns()
            unmasked = qr._Matrix(version)
            unmasked.draw_function_patterns()
            unmasked.dark = [row[:] for row in reference]
            unmasked.apply_mask(mask)
            matrix.draw_codewords(_read_codewords(unmasked))
            matrix.apply_mask(mask)
            matrix.draw_format(mask)
            assert matrix.dark == reference, (text[:10], mask)
            own = qr._codewords(text.encode(), version)
            assert _read_codewords(unmasked)[:len(own)][:3] == own[:3]


def _read_codewords(matrix) -> list[int]:
    bits, right = [], matrix.size - 1
    while right >= 1:
        if right == 6:
            right = 5
        for vert in range(matrix.size):
            for j in range(2):
                x = right - j
                y = matrix.size - 1 - vert if ((right + 1) & 2) == 0 else vert
                if not matrix.function[y][x]:
                    bits.append(int(matrix.dark[y][x]))
        right -= 2
    return [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits) // 8 * 8, 8)]


GOLDEN_URL_MASK2 = "7cb7d0e41c966a93d65ae7bd1640cece4661ba924bcbd34290da31e2445fa95c"
