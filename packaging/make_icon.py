"""Draw the app icon (atc/app/static/icon.svg: a ring, four ticks and a needle) as packaging/icon.ico.

numpy only, no image library: each pixel's distance to the shapes gives its coverage (anti-aliased), and the ICO
holds one PNG per size. Run: .venv\\Scripts\\python packaging\\make_icon.py
"""
import struct
import zlib
from pathlib import Path

import numpy as np

COLOR = (0xF0, 0xA8, 0x3C)  # the SVG's stroke
STROKE = 1.5  # in the SVG's 24-unit box
SIZES = (16, 24, 32, 48, 64, 256)
SEGMENTS = [((12, 3), (12, 6)), ((12, 18), (12, 21)), ((3, 12), (6, 12)), ((18, 12), (21, 12)), ((12, 12), (17, 7))]


def segment_distance(x, y, a, b):
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = np.clip(((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy), 0, 1)
    return np.hypot(x - (ax + t * dx), y - (ay + t * dy))


def draw(size: int) -> np.ndarray:
    """RGBA, size x size."""
    scale = size / 24
    y, x = (np.mgrid[0:size, 0:size] + 0.5) / scale  # pixel centres in SVG units
    distance = np.abs(np.hypot(x - 12, y - 12) - 9)  # the ring
    for a, b in SEGMENTS:
        distance = np.minimum(distance, segment_distance(x, y, a, b))  # round caps come with the distance
    half = max(STROKE, 1.2 / scale) / 2  # small icons: at least about a pixel wide
    alpha = np.clip((half - distance) * scale + 0.5, 0, 1)
    image = np.zeros((size, size, 4), np.uint8)
    image[..., :3] = COLOR
    image[..., 3] = np.round(alpha * 255)
    return image


def png(image: np.ndarray) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    h, w = image.shape[:2]
    raw = b"".join(b"\x00" + image[row].tobytes() for row in range(h))  # filter 0 on every row
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def ico(images: list[bytes], sizes) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, image in zip(sizes, images):
        side = 0 if size >= 256 else size  # 0 means 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset + len(data))
        data += image
    return header + entries + data


if __name__ == "__main__":
    target = Path(__file__).parent / "icon.ico"
    target.write_bytes(ico([png(draw(s)) for s in SIZES], SIZES))
    print(f"{target} ({target.stat().st_size} bytes)")
