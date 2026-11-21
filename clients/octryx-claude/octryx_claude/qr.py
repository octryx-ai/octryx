"""A small QR code encoder (ISO/IEC 18004, byte mode, error correction level M, versions 1-20), no dependencies.

It draws the pairing code of ``octryx-claude mobile pair`` in the terminal and in the pet. Only what a URL needs is
implemented: one byte-mode segment, level M, the smallest version that fits. The structure follows Project Nayuki's
reference implementation; ``tests/test_qr.py`` compares the matrices with the ``segno`` library module by module.

:func:`encode` returns the module matrix (``rows[y][x]``, ``True`` = dark) without the quiet zone;
:func:`terminal_lines` renders it with half blocks (two module rows per text line) inside a 2-module quiet zone.
"""

from __future__ import annotations

MAX_VERSION = 20
# Level M, indexed by version (0 unused): error correction codewords per block and number of blocks.
_ECC_PER_BLOCK_M = (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26)
_BLOCKS_M = (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16)
_FORMAT_BITS_M = 0  # the two format bits of level M
_PAD = (0xEC, 0x11)


class QrTooLongError(ValueError):
    pass


def _raw_data_modules(version: int) -> int:
    result = (16 * version + 128) * version + 64
    if version >= 2:
        count = version // 7 + 2
        result -= (25 * count - 10) * count - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version: int) -> int:
    return _raw_data_modules(version) // 8 - _ECC_PER_BLOCK_M[version] * _BLOCKS_M[version]


def _gf_multiply(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _gf_multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _gf_multiply(root, 0x02)
    return result


def _rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _gf_multiply(coefficient, factor)
    return result


def _codewords(payload: bytes, version: int) -> list[int]:
    capacity = _data_codewords(version)
    bits: list[int] = []

    def put(value: int, length: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(length)))

    put(0b0100, 4)  # byte mode
    put(len(payload), 8 if version <= 9 else 16)
    for byte in payload:
        put(byte, 8)
    put(0, min(4, capacity * 8 - len(bits)))
    put(0, -len(bits) % 8)
    data = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    data += [_PAD[i % 2] for i in range(capacity - len(data))]

    blocks_count, ecc_len = _BLOCKS_M[version], _ECC_PER_BLOCK_M[version]
    raw = _raw_data_modules(version) // 8
    short_blocks = blocks_count - raw % blocks_count
    short_len = raw // blocks_count
    divisor = _rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(blocks_count):
        size = short_len - ecc_len + (0 if i < short_blocks else 1)
        chunk = data[k:k + size]
        k += size
        ecc = _rs_remainder(chunk, divisor)
        if i < short_blocks:
            chunk.append(0)
        blocks.append(chunk + ecc)
    result = []
    for i in range(len(blocks[0])):
        for j, block in enumerate(blocks):
            if i != short_len - ecc_len or j >= short_blocks:
                result.append(block[i])
    return result


class _Matrix:
    def __init__(self, version: int) -> None:
        self.version = version
        self.size = version * 4 + 17
        self.dark = [[False] * self.size for _ in range(self.size)]
        self.function = [[False] * self.size for _ in range(self.size)]

    def set_function(self, x: int, y: int, dark: bool) -> None:
        self.dark[y][x] = dark
        self.function[y][x] = True

    def alignment_positions(self) -> list[int]:
        if self.version == 1:
            return []
        count = self.version // 7 + 2
        step = (self.version * 8 + count * 3 + 5) // (count * 4 - 4) * 2
        return list(reversed([self.size - 7 - i * step for i in range(count - 1)] + [6]))

    def draw_function_patterns(self) -> None:
        for i in range(self.size):
            self.set_function(6, i, i % 2 == 0)
            self.set_function(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (self.size - 4, 3), (3, self.size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < self.size and 0 <= y < self.size:
                        self.set_function(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = self.alignment_positions()
        last = len(positions) - 1
        for i, cx in enumerate(positions):
            for j, cy in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_function(cx + dx, cy + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        if self.version >= 7:
            rem = self.version
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.version << 12 | rem
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a, b = self.size - 11 + i % 3, i // 3
                self.set_function(a, b, dark)
                self.set_function(b, a, dark)

    def draw_format(self, mask: int) -> None:
        data = _FORMAT_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i: int) -> bool:
            return (bits >> i) & 1 == 1

        for i in range(6):
            self.set_function(8, i, bit(i))
        self.set_function(8, 7, bit(6))
        self.set_function(8, 8, bit(7))
        self.set_function(7, 8, bit(8))
        for i in range(9, 15):
            self.set_function(14 - i, 8, bit(i))
        for i in range(8):
            self.set_function(self.size - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_function(8, self.size - 15 + i, bit(i))
        self.set_function(8, self.size - 8, True)

    def draw_codewords(self, data: list[int]) -> None:
        i = 0
        right = self.size - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(self.size):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = self.size - 1 - vert if upward else vert
                    if not self.function[y][x] and i < len(data) * 8:
                        self.dark[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.function[y][x]:
                    continue
                if mask == 0:
                    flip = (x + y) % 2 == 0
                elif mask == 1:
                    flip = y % 2 == 0
                elif mask == 2:
                    flip = x % 3 == 0
                elif mask == 3:
                    flip = (x + y) % 3 == 0
                elif mask == 4:
                    flip = (x // 3 + y // 2) % 2 == 0
                elif mask == 5:
                    flip = x * y % 2 + x * y % 3 == 0
                elif mask == 6:
                    flip = (x * y % 2 + x * y % 3) % 2 == 0
                else:
                    flip = ((x + y) % 2 + x * y % 3) % 2 == 0
                if flip:
                    self.dark[y][x] = not self.dark[y][x]

    def penalty(self) -> int:
        """ISO penalty rules 1, 2 and 4 (rule 3, finder-like runs, only fine-tunes the choice)."""
        score, size, dark = 0, self.size, self.dark
        for lines in (dark, [list(col) for col in zip(*dark, strict=True)]):
            for line in lines:
                run = 1
                for a, b in zip(line, line[1:], strict=False):
                    if a == b:
                        run += 1
                    else:
                        score += run - 2 if run >= 5 else 0
                        run = 1
                score += run - 2 if run >= 5 else 0
        for y in range(size - 1):
            for x in range(size - 1):
                if dark[y][x] == dark[y][x + 1] == dark[y + 1][x] == dark[y + 1][x + 1]:
                    score += 3
        total = sum(map(sum, dark))
        score += (abs(total * 20 - size * size * 10) // (size * size)) * 10
        return score


def encode(text: str, *, mask: int | None = None) -> list[list[bool]]:
    payload = text.encode("utf-8")
    for version in range(1, MAX_VERSION + 1):
        if len(payload) + (2 if version <= 9 else 3) <= _data_codewords(version):
            break
    else:
        raise QrTooLongError(f"{len(payload)} bytes do not fit a version {MAX_VERSION} QR code")
    codewords = _codewords(payload, version)
    best: tuple[int, list[list[bool]]] | None = None
    for candidate in ([mask] if mask is not None else range(8)):
        matrix = _Matrix(version)
        matrix.draw_function_patterns()
        matrix.draw_codewords(codewords)
        matrix.apply_mask(candidate)
        matrix.draw_format(candidate)
        score = matrix.penalty()
        if best is None or score < best[0]:
            best = (score, matrix.dark)
    assert best is not None
    return best[1]


def terminal_lines(rows: list[list[bool]], *, quiet: int = 4) -> list[str]:
    """Half blocks, two module rows per text line. Light modules (and the quiet zone) are drawn as blocks in the
    terminal's text colour and dark modules are left as background: on the usual dark terminal that is the normal
    dark-on-light code; phone cameras also read the inverted one a light terminal shows."""
    size = len(rows)
    total = size + 2 * quiet

    def light(x: int, y: int) -> bool:
        inside = quiet <= x < quiet + size and quiet <= y < quiet + size
        return not (inside and rows[y - quiet][x - quiet])

    lines = []
    for y in range(0, total, 2):
        line = []
        for x in range(total):
            top = light(x, y)
            bottom = light(x, y + 1) if y + 1 < total else False
            line.append({(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}[(top, bottom)])
        lines.append("".join(line))
    return lines


__all__ = ["QrTooLongError", "encode", "terminal_lines"]
