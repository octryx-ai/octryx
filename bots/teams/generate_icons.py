"""
Generate placeholder Teams bot icons using only the stdlib (no Pillow needed).
Produces:
  manifest/color.png   – 192 × 192 px, blue background + "OX" text (PNG via struct/zlib)
  manifest/outline.png – 32 × 32 px, white transparent outline circle

Run once:
    python generate_icons.py

Then replace with your real brand icons before distributing the app.
"""

import struct
import zlib
from pathlib import Path


def _make_png(width: int, height: int, pixels_rgb: list[tuple[int, int, int]]) -> bytes:
    """Build a minimal RGB PNG from a flat list of (r, g, b) tuples."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b""
    for y in range(height):
        raw += b"\x00"  # filter type None
        for x in range(width):
            r, g, b = pixels_rgb[y * width + x]
            raw += bytes([r, g, b])

    compressed = zlib.compress(raw, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def _make_png_rgba(width: int, height: int, pixels_rgba: list[tuple[int, int, int, int]]) -> bytes:
    """Build a minimal RGBA PNG from a flat list of (r, g, b, a) tuples."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw = b""
    for y in range(height):
        raw += b"\x00"
        for x in range(width):
            r, g, b, a = pixels_rgba[y * width + x]
            raw += bytes([r, g, b, a])

    compressed = zlib.compress(raw, 9)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )


def generate_color_icon(path: Path, size: int = 192) -> None:
    """Blue circular background with white 'OX' label."""
    bg = (0, 120, 212)   # #0078D4 – Microsoft blue
    fg = (255, 255, 255)

    pixels: list[tuple[int, int, int]] = []
    cx, cy, r = size // 2, size // 2, size // 2 - 4  # circle radius

    # Simple 5×5 pixel font for "OX"
    letter_o = [
        " ### ",
        "#   #",
        "#   #",
        "#   #",
        " ### ",
    ]
    letter_x = [
        "#   #",
        " # # ",
        "  #  ",
        " # # ",
        "#   #",
    ]

    def in_circle(x: int, y: int) -> bool:
        return (x - cx) ** 2 + (y - cy) ** 2 <= r ** 2

    scale = size // 20
    o_cols, x_cols = len(letter_o[0]), len(letter_x[0])
    total_w = (o_cols + 1 + x_cols) * scale
    total_h = 5 * scale
    ox = cx - total_w // 2
    oy = cy - total_h // 2

    glyph_pixels: set[tuple[int, int]] = set()
    for row, line in enumerate(letter_o):
        for col, ch in enumerate(line):
            if ch != " ":
                for dy in range(scale):
                    for dx in range(scale):
                        glyph_pixels.add((ox + col * scale + dx, oy + row * scale + dy))
    x_offset = ox + (o_cols + 1) * scale
    for row, line in enumerate(letter_x):
        for col, ch in enumerate(line):
            if ch != " ":
                for dy in range(scale):
                    for dx in range(scale):
                        glyph_pixels.add((x_offset + col * scale + dx, oy + row * scale + dy))

    for y in range(size):
        for x in range(size):
            if not in_circle(x, y):
                pixels.append((255, 255, 255))
            elif (x, y) in glyph_pixels:
                pixels.append(fg)
            else:
                pixels.append(bg)

    path.write_bytes(_make_png(size, size, pixels))
    print(f"  Created {path}  ({size}×{size} px)")


def generate_outline_icon(path: Path, size: int = 32) -> None:
    """White circle outline on transparent background."""
    pixels: list[tuple[int, int, int, int]] = []
    cx = cy = size / 2
    outer_r = size / 2 - 2
    inner_r = outer_r - 3

    for y in range(size):
        for x in range(size):
            dist = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
            if inner_r <= dist <= outer_r:
                pixels.append((255, 255, 255, 255))
            else:
                pixels.append((0, 0, 0, 0))

    path.write_bytes(_make_png_rgba(size, size, pixels))
    print(f"  Created {path}  ({size}×{size} px)")


if __name__ == "__main__":
    out = Path(__file__).parent / "manifest"
    out.mkdir(exist_ok=True)
    print("Generating Teams bot icons …")
    generate_color_icon(out / "color.png")
    generate_outline_icon(out / "outline.png")
    print("Done. Replace with brand icons before distributing.")
