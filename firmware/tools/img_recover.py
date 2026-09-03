#!/usr/bin/env python3
"""img_recover.py — downlink a camera frame and write it as a PNG.

The probe never puts pixels in telemetry (spec §6.1): only capture
statistics ride the downlink. Recovering the actual picture means reading
the frame buffer out over the uplink, 64 bytes per PEEK — the same slow,
deliberate downlink a real deep-space image takes. This tool automates
that and renders the result.

    img_recover.py                          capture and recover as built
    img_recover.py --target 2               retarget first (comet field)
    img_recover.py --invert                 install an inverting LUT first
    img_recover.py --filter blur|sharpen|edge|threshold
    img_recover.py -o out.png --scale 6

Everything it does is an ordinary uplink command, so anything here is
something a player can do by hand from the console.
"""
import argparse
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from png import write_gray_png                                  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CAM_BASE = 0x2001E100
CAM_CCTRL = CAM_BASE + 0x00
CAM_TARGET = CAM_BASE + 0x08
CAM_FRAME_ID = CAM_BASE + 0x14
CAM_FRAME_ADDR = CAM_BASE + 0x18
CAM_FRAME_LEN = CAM_BASE + 0x1C
W = H = 64

KERNELS = {                       # name: (9 coefficients, divisor)
    "blur":      ([1, 1, 1, 1, 1, 1, 1, 1, 1], 9),
    "sharpen":   ([0, -1, 0, -1, 5, -1, 0, -1, 0], 1),
    "edge":      ([-1, -1, -1, -1, 8, -1, -1, -1, -1], 1),
}


def crc16(s: str) -> int:
    c = 0xFFFF
    for b in s.encode():
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ 0x1021) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


class Link:
    """One uplink/downlink session with the probe."""

    def __init__(self, sock):
        self.s = sock
        self.s.settimeout(0.4)
        self.buf = b""

    def _line(self, timeout=6.0):
        end = time.time() + timeout
        while time.time() < end:
            if b"\n" in self.buf:
                ln, self.buf = self.buf.split(b"\n", 1)
                t = ln.decode(errors="replace").strip()
                if t:
                    return t
                continue
            try:
                d = self.s.recv(4096)
                if d:
                    self.buf += d
            except socket.timeout:
                pass
        return None

    def cmd(self, text, timeout=6.0):
        self.s.sendall(f"{text} *{crc16(text + ' '):04X}\r\n".encode())
        end = time.time() + timeout
        while time.time() < end:
            ln = self._line(min(1.0, max(0.05, end - time.time())))
            if ln and ln.startswith(("ACK", "NAK")):
                return ln
        return None

    def peek(self, addr, n):
        r = self.cmd(f"PEEK 0x{addr:08X} {n}")
        if not r or not r.startswith("ACK PEEK"):
            raise RuntimeError(f"PEEK failed at 0x{addr:08X}: {r}")
        return bytes.fromhex(r.split()[-1])

    def poke(self, addr, data: bytes):
        r = self.cmd(f"POKE 0x{addr:08X} {data.hex().upper()}")
        if not r or not r.startswith("ACK POKE"):
            raise RuntimeError(f"POKE failed at 0x{addr:08X}: {r}")

    def poke_long(self, addr, data: bytes, chunk=32):
        for off in range(0, len(data), chunk):
            self.poke(addr + off, data[off:off + chunk])

    def u32(self, addr):
        return int.from_bytes(self.peek(addr, 4), "little")


def install_lut(link, curve, base):
    """Write a 256-entry transfer curve; 32 bytes per uplink."""
    link.poke_long(base, bytes(curve))


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--connect", metavar="HOST:PORT",
                    help="attach to a running probe (default: spawn QEMU)")
    ap.add_argument("--target", type=int, help="retarget the camera first (0-7)")
    ap.add_argument("--invert", action="store_true",
                    help="install an inverting LUT before capturing")
    ap.add_argument("--threshold", type=int, metavar="T",
                    help="install a hard-threshold LUT at T")
    ap.add_argument("--filter", choices=sorted(KERNELS),
                    help="install a 3x3 convolution kernel")
    ap.add_argument("--lut-addr", type=lambda v: int(v, 0),
                    help="address of cam_lut (default: read build/symbols.json)")
    ap.add_argument("--kernel-addr", type=lambda v: int(v, 0),
                    help="address of cam_kernel")
    ap.add_argument("--filter-addr", type=lambda v: int(v, 0),
                    help="address of the cam_filter config byte")
    ap.add_argument("-o", "--out", default="frame.png")
    ap.add_argument("--scale", type=int, default=6, help="PNG upscale factor")
    args = ap.parse_args()

    qemu = None
    if args.connect:
        host, port = args.connect.rsplit(":", 1)
        sock = socket.create_connection((host, int(port)), 10)
    else:
        port = 5615
        qemu = subprocess.Popen(
            ["qemu-system-arm", "-M", "mps2-an386", "-nographic", "-monitor", "none",
             "-kernel", str(ROOT / "build" / "probe_rom.elf"),
             "-serial", f"tcp:127.0.0.1:{port},server=on,wait=on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        sock = None
        for _ in range(40):
            try:
                sock = socket.create_connection(("127.0.0.1", port), 1)
                break
            except OSError:
                time.sleep(0.25)
        if sock is None:
            sys.exit("could not reach the probe")

    try:
        link = Link(sock)
        time.sleep(1.0)
        if not link.cmd("PING"):
            sys.exit("probe not answering")

        if args.target is not None:
            link.poke(CAM_TARGET, bytes([args.target & 7, 0, 0, 0]))
            print(f"retargeted to catalog entry {args.target & 7}")

        if args.invert or args.threshold is not None or args.filter:
            import json
            syms = {}
            sym_path = ROOT / "build" / "symbols.json"
            if sym_path.exists():
                syms = json.load(open(sym_path))["symbols"]
            lut = args.lut_addr or int(syms.get("cam_lut", "0"), 16)
            ker = args.kernel_addr or int(syms.get("cam_kernel", "0"), 16)
            if args.invert:
                if not lut:
                    sys.exit("need --lut-addr (no symbols.json)")
                install_lut(link, [255 - i for i in range(256)], lut)
                print(f"installed inverting LUT at 0x{lut:08X}")
            if args.threshold is not None:
                if not lut:
                    sys.exit("need --lut-addr")
                t = args.threshold
                install_lut(link, [0 if i < t else 255 for i in range(256)], lut)
                print(f"installed threshold LUT (T={t}) at 0x{lut:08X}")
            if args.filter:
                if not ker:
                    sys.exit("need --kernel-addr")
                coeffs, div = KERNELS[args.filter]
                link.poke(ker, bytes((c & 0xFF) for c in coeffs))
                if args.filter_addr:
                    link.poke(args.filter_addr, bytes([0x03]))   # LUT|CONV
                print(f"installed {args.filter} kernel at 0x{ker:08X} (div {div})")

        before = link.u32(CAM_FRAME_ID)
        link.poke(CAM_CCTRL, bytes([0x03]))            # CAPTURE_NOW | AUTO
        for _ in range(20):
            time.sleep(0.5)
            if link.u32(CAM_FRAME_ID) != before:
                break
        else:
            sys.exit("capture did not complete")

        addr = link.u32(CAM_FRAME_ADDR)
        size = min(link.u32(CAM_FRAME_LEN), W * H)
        print(f"frame {link.u32(CAM_FRAME_ID)} at 0x{addr:08X}, {size} bytes "
              f"-> {size // 64} PEEK commands")

        px = bytearray()
        for off in range(0, size, 64):
            px += link.peek(addr + off, min(64, size - off))
            if (off // 64) % 16 == 0:
                print(f"  ...{len(px)}/{size} bytes", flush=True)

        write_gray_png(args.out, W, H, bytes(px), scale=args.scale)
        print(f"wrote {args.out}  ({W}x{H}, x{args.scale})")
    finally:
        if qemu:
            qemu.kill()


if __name__ == "__main__":
    main()
