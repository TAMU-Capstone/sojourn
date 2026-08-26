#!/usr/bin/env python3
"""fixup_app.py — finalize the golden application image header.

The app links with size=0, crc=0 in its apphdr (offsets 8 and 12).  This
tool sets size = file length and crc32 = CRC over everything after the
16-byte header, matching the bootloader's check in boot.c.
"""
import struct
import sys
import zlib

APPHDR_MAGIC = 0x4E4A5253  # 'SRJN'

def main(src: str, dst: str) -> None:
    data = bytearray(open(src, "rb").read())
    if len(data) < 16:
        sys.exit("image too small")
    magic, = struct.unpack_from("<I", data, 0)
    if magic != APPHDR_MAGIC:
        sys.exit(f"bad app header magic: {magic:#x}")
    size = len(data)
    crc = zlib.crc32(bytes(data[16:size])) & 0xFFFFFFFF
    struct.pack_into("<II", data, 8, size, crc)
    open(dst, "wb").write(data)
    print(f"{dst}: {size} bytes, crc32={crc:#010x}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
