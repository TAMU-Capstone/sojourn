"""png.py — minimal 8-bit grayscale PNG writer (stdlib only, no PIL).

Used by the ground-side image tools so students need no extra packages.
"""
import struct
import zlib


def write_gray_png(path, width, height, pixels, scale=1):
    """pixels: bytes/bytearray of length width*height, 8-bit grayscale."""
    if len(pixels) < width * height:
        pixels = bytes(pixels) + b"\x00" * (width * height - len(pixels))
    if scale > 1:                                   # nearest-neighbour upscale
        big = bytearray(width * scale * height * scale)
        for y in range(height):
            row = pixels[y * width:(y + 1) * width]
            up = bytearray()
            for v in row:
                up.extend(bytes([v]) * scale)
            for r in range(scale):
                off = (y * scale + r) * width * scale
                big[off:off + width * scale] = up
        pixels, width, height = bytes(big), width * scale, height * scale

    raw = b"".join(b"\x00" + bytes(pixels[y * width:(y + 1) * width])
                   for y in range(height))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)
    return path
