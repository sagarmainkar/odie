"""A small QR code encoder for pairing links: byte mode, error correction level M, versions 1-10 (up to 213 bytes), and
an SVG of the result. It follows the standard algorithm (ISO/IEC 18004): data codewords, Reed-Solomon error
correction in blocks, interleaving, the fixed patterns, zigzag placement, and the mask with the lowest penalty."""
from __future__ import annotations

# Error correction level M, by version 1-10 (index 0 unused).
ECC_PER_BLOCK = [0, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26]
BLOCKS = [0, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5]
ALIGN = [[], [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50]]
MAX_VERSION = 10
ECL_BITS_M = 0b00


def raw_modules(ver: int) -> int:
    """Modules available for data and error correction (everything but the fixed patterns)."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        n = ver // 7 + 2
        result -= (25 * n - 10) * n - 55
        if ver >= 7:
            result -= 36
    return result


def data_codewords(ver: int) -> int:
    return raw_modules(ver) // 8 - ECC_PER_BLOCK[ver] * BLOCKS[ver]


def _count_bits(ver: int) -> int:
    return 8 if ver <= 9 else 16


def version_for(data: bytes) -> int:
    for ver in range(1, MAX_VERSION + 1):
        if 4 + _count_bits(ver) + 8 * len(data) <= data_codewords(ver) * 8:
            return ver
    raise ValueError(f"too long for a QR code here ({len(data)} bytes)")


# ── Reed-Solomon over GF(256), polynomial 0x11D ──
def _mul(x: int, y: int) -> int:
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _mul(root, 0x02)
    return result


def rs_remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _mul(coef, factor)
    return result


def codewords(data: bytes, ver: int) -> list[int]:
    """The data codewords (mode, count, bytes, terminator, padding), split into blocks with their error correction,
    interleaved."""
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in reversed(range(n)))
    put(0b0100, 4)
    put(len(data), _count_bits(ver))
    for b in data:
        put(b, 8)
    cap = data_codewords(ver) * 8
    put(0, min(4, cap - len(bits)))
    put(0, (-len(bits)) % 8)
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]
    pad = 0xEC
    while len(words) < data_codewords(ver):
        words.append(pad)
        pad ^= 0xEC ^ 0x11
    n_blocks, ecc_len = BLOCKS[ver], ECC_PER_BLOCK[ver]
    raw = raw_modules(ver) // 8
    short = n_blocks - raw % n_blocks
    short_len = raw // n_blocks
    divisor = rs_divisor(ecc_len)
    blocks, k = [], 0
    for i in range(n_blocks):
        size = short_len - ecc_len + (0 if i < short else 1)
        dat = words[k:k + size]
        k += size
        ecc = rs_remainder(dat, divisor)
        if i < short:
            dat = dat + [0]  # a place holder, skipped when interleaving
        blocks.append(dat + ecc)
    out = []
    for i in range(len(blocks[0])):
        for j, blk in enumerate(blocks):
            if i != short_len - ecc_len or j >= short:
                out.append(blk[i])
    return out


# ── the matrix ──
class _Grid:
    def __init__(self, ver: int) -> None:
        self.ver = ver
        self.size = ver * 4 + 17
        self.m = [[False] * self.size for _ in range(self.size)]
        self.fixed = [[False] * self.size for _ in range(self.size)]

    def set(self, x: int, y: int, dark: bool) -> None:
        self.m[y][x] = dark
        self.fixed[y][x] = True

    def patterns(self) -> None:
        s = self.size
        for i in range(s):
            self.set(6, i, i % 2 == 0)
            self.set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = ALIGN[self.ver]
        last = len(pos) - 1
        for i, ay in enumerate(pos):
            for j, ax in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue  # the finder patterns are there
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.format(0)  # reserved now, drawn for real once the mask is chosen
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a, b = s - 11 + i % 3, i // 3
                self.set(a, b, dark)
                self.set(b, a, dark)

    def format(self, mask: int) -> None:
        data = ECL_BITS_M << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412
        bit = lambda i: (bits >> i) & 1 == 1  # noqa: E731
        s = self.size
        for i in range(6):
            self.set(8, i, bit(i))
        self.set(8, 7, bit(6))
        self.set(8, 8, bit(7))
        self.set(7, 8, bit(8))
        for i in range(9, 15):
            self.set(14 - i, 8, bit(i))
        for i in range(8):
            self.set(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set(8, s - 15 + i, bit(i))
        self.set(8, s - 8, True)

    def place(self, words: list[int]) -> None:
        s, i = self.size, 0
        right = s - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    upward = ((right + 1) & 2) == 0
                    y = s - 1 - vert if upward else vert
                    if not self.fixed[y][x] and i < len(words) * 8:
                        self.m[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply(self, mask: int) -> None:
        for y in range(self.size):
            for x in range(self.size):
                if self.fixed[y][x]:
                    continue
                flip = [(x + y) % 2 == 0, y % 2 == 0, x % 3 == 0, (x + y) % 3 == 0, (x // 3 + y // 2) % 2 == 0,
                        x * y % 2 + x * y % 3 == 0, (x * y % 2 + x * y % 3) % 2 == 0, ((x + y) % 2 + x * y % 3) % 2 == 0][mask]
                if flip:
                    self.m[y][x] = not self.m[y][x]

    def penalty(self) -> int:
        """Runs of five or more, 2x2 blocks, and the balance of dark and light (the finder-like rule is left out: it
        only nudges the choice, and any mask decodes)."""
        s, m, score = self.size, self.m, 0
        for lines in (m, [list(col) for col in zip(*m)]):
            for row in lines:
                run, last = 0, None
                for v in row:
                    if v == last:
                        run += 1
                        if run == 5:
                            score += 3
                        elif run > 5:
                            score += 1
                    else:
                        run, last = 1, v
        for y in range(s - 1):
            for x in range(s - 1):
                if m[y][x] == m[y][x + 1] == m[y + 1][x] == m[y + 1][x + 1]:
                    score += 3
        dark = sum(sum(row) for row in m)
        total = s * s
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        return score + max(0, k) * 10


def encode(text: str) -> list[list[bool]]:
    data = text.encode("utf-8")
    ver = version_for(data)
    words = codewords(data, ver)
    best, best_score = None, None
    for mask in range(8):
        g = _Grid(ver)
        g.patterns()
        g.place(words)
        g.apply(mask)
        g.format(mask)
        score = g.penalty()
        if best_score is None or score < best_score:
            best, best_score = g, score
    return best.m


def svg(matrix: list[list[bool]], scale: int = 8, border: int = 4) -> str:
    size = len(matrix) + border * 2
    cells = "".join(f"M{x + border},{y + border}h1v1h-1z" for y, row in enumerate(matrix) for x, dark in enumerate(row) if dark)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size * scale}" height="{size * scale}" '
            f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/><path d="{cells}" fill="#000"/></svg>')
