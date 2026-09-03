"""png.py — minimal 8-bit grayscale PNG writer (stdlib only, no PIL).

Used by the ground-side image tools so students need no extra packages.
"""
import struct
import zlib


def read_gray_png(path):
    """Decode a PNG to (width, height, grayscale bytes). Stdlib only."""
    d = open(path, "rb").read()
    pos, idat, plte = 8, b"", None
    w = h = bd = ct = 0
    while pos < len(d):
        ln = struct.unpack(">I", d[pos:pos + 4])[0]
        tag = d[pos + 4:pos + 8]
        data = d[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif tag == b"IDAT":
            idat += data
        elif tag == b"PLTE":
            plte = data
        elif tag == b"IEND":
            break
    if bd != 8:
        raise ValueError(f"{path}: only 8-bit PNGs supported (got {bd})")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(w * h)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        for i in range(stride):                       # undo row filter
            a = line[i - ch] if i >= ch else 0
            b = prev[i]
            c = prev[i - ch] if i >= ch else 0
            x = line[i]
            if f == 1:
                x = (x + a) & 0xFF
            elif f == 2:
                x = (x + b) & 0xFF
            elif f == 3:
                x = (x + ((a + b) >> 1)) & 0xFF
            elif f == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                x = (x + pr) & 0xFF
            line[i] = x
        prev = line
        for x0 in range(w):                           # to luminance
            if ct == 3:
                i = line[x0]; r, g, bl = plte[i * 3:i * 3 + 3]
            elif ct == 0:
                r = g = bl = line[x0]
            elif ct == 4:
                r = g = bl = line[x0 * 2]
            else:
                r, g, bl = line[x0 * ch], line[x0 * ch + 1], line[x0 * ch + 2]
            out[y * w + x0] = (r * 299 + g * 587 + bl * 114) // 1000
    return w, h, bytes(out)


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
