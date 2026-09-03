#!/usr/bin/env python3
"""e2e_test.py — end-to-end verification of the Sojourn reference firmware.

Boots the ROM under QEMU (mps2-an386), talks to the probe over its UART
(TCP serial) and over the GDB stub (raw RSP), and verifies the behaviors
the platform will build on:

  1  boot banner + telemetry framing (sync, CRC, channel decode)
  2  PING / STAT / NOOP round-trips, bad-CRC NAK E01, unknown-verb E02
  3  PEEK of the sensor block; live sensor data via the GDB stub
  4  POKE protection: ROM -> E04, system RAM -> E04, unmapped -> E03
  5  Objective 1 flow: POKE MAG CTRL off -> channel vanishes, load drops
  6  Camera: CAPTURE_NOW -> frame_id, stats, channel 0x43; exposure change
     moves SAT_PCT/STARS the right way
  7  Brick + recovery: disable the wdg_pet task via the task table ->
     watchdog reset within ~3 s -> reboots+1, uptime reset, patches gone

Run from firmware/:  python3 tools/e2e_test.py
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QEMU_BIN = os.environ.get("QEMU_BIN", "qemu-system-arm")
SER_PORT = int(os.environ.get("SER_PORT", 5599))
GDB_PORT = int(os.environ.get("GDB_PORT", 3344))

SENS_BASE = 0x2001E000
CAM_BASE = 0x2001E100
SLOT = {"MAG": 0, "IMU": 1, "THM": 2, "PWR": 3, "RAD": 4, "STR": 5, "CAM": 6}

passed, failed = 0, 0
def check(name, cond, detail=""):
    global passed, failed
    ok = bool(cond)
    passed += ok; failed += (not ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))
    return ok

def crc16(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc

# ---------------- serial (probe UART over TCP) ----------------
class Probe:
    def __init__(self):
        self.buf = b""
        self.sock = None

    def connect(self):
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", SER_PORT), 1)
                self.sock.settimeout(0.2)
                return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("cannot connect to QEMU serial")

    def readline(self, timeout=10.0):
        end = time.time() + timeout
        while time.time() < end:
            if b"\n" in self.buf:
                line, self.buf = self.buf.split(b"\n", 1)
                s = line.decode(errors="replace").strip()
                if s:
                    return s
                continue
            try:
                d = self.sock.recv(4096)
                if d:
                    self.buf += d
            except socket.timeout:
                pass
        return None

    def wait_for(self, pred, timeout=15.0):
        end = time.time() + timeout
        while time.time() < end:
            line = self.readline(min(2.0, max(0.1, end - time.time())))
            if line is not None and pred(line):
                return line
        return None

    def cmd(self, text, timeout=5.0):
        """Send with correct CRC; return first ACK/NAK line."""
        full = f"{text} *{crc16(text.encode() + b' '):04X}\r\n"
        self.sock.sendall(full.encode())
        return self.wait_for(lambda l: l.startswith(("ACK", "NAK")), timeout)

    def raw(self, text, timeout=5.0):
        self.sock.sendall((text + "\r\n").encode())
        return self.wait_for(lambda l: l.startswith(("ACK", "NAK")), timeout)

# ---------------- telemetry decoding ----------------
def parse_tlm(line):
    if not line.startswith("TLM "):
        return None
    raw = bytes.fromhex(line[4:])
    if len(raw) < 5 or raw[0] != 0xEB or raw[1] != 0x90:
        return None
    paylen = raw[2]
    payload = raw[3:3 + paylen]
    crc = int.from_bytes(raw[3 + paylen:5 + paylen], "big")
    if crc16(raw[2:3 + paylen]) != crc:
        return {"crc_ok": False}
    f = {
        "crc_ok": True,
        "frame": int.from_bytes(payload[0:2], "big"),
        "uptime": int.from_bytes(payload[2:6], "big"),
        "mode": payload[6], "reboots": payload[7], "fault": payload[8],
        "bus_mv": int.from_bytes(payload[9:11], "big"),
        "load_mw": int.from_bytes(payload[11:13], "big"),
        "ch": {},
    }
    i = 13
    while i + 2 <= len(payload):
        cid, clen = payload[i], payload[i + 1]
        f["ch"][cid] = payload[i + 2:i + 2 + clen]
        i += 2 + clen
    return f

def next_tlm(p, timeout=12.0):
    line = p.wait_for(lambda l: l.startswith("TLM "), timeout)
    return parse_tlm(line) if line else None

# ---------------- GDB remote serial protocol ----------------
def gdb_read_mem(addr, length):
    """One-shot: connect (halts VM), read, detach (resumes)."""
    s = socket.create_connection(("127.0.0.1", GDB_PORT), 5)
    s.settimeout(3)
    def send(payload):
        cs = sum(payload.encode()) & 0xFF
        s.sendall(f"+${payload}#{cs:02x}".encode())
    def recv_packet():
        data = b""
        while True:
            d = s.recv(4096)
            if not d:
                return None
            data += d
            if b"#" in data and len(data) >= data.index(b"#") + 3:
                start = data.index(b"$") + 1
                return data[start:data.index(b"#")].decode()
    send(f"m{addr:08x},{length:x}")
    reply = recv_packet()
    send("D")               # detach: VM resumes
    try:
        s.recv(64)
    except OSError:
        pass
    s.close()
    return bytes.fromhex(reply) if reply and "E" != reply[:1] else None

# ---------------- the test run ----------------
def main():
    subprocess.run(["make", "-C", str(ROOT)], check=True, capture_output=True)
    symbols = json.load(open(ROOT / "build" / "symbols.json"))["symbols"]
    task_table = int(symbols["task_table"], 16)

    qemu = subprocess.Popen(
        [QEMU_BIN, "-M", "mps2-an386", "-nographic", "-monitor", "none",
         "-kernel", str(ROOT / "build" / "probe_rom.elf"),
         "-serial", f"tcp:127.0.0.1:{SER_PORT},server=on,wait=on",
         "-gdb", f"tcp::{GDB_PORT}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        p = Probe()
        p.connect()

        print("== 1. boot & telemetry framing ==")
        banner = p.wait_for(lambda l: "SOJOURN FSW" in l, 15)
        check("boot banner", banner and "reboots=0" in banner, banner)
        f = next_tlm(p)
        check("telemetry frame CRC", f and f["crc_ok"])
        check("nominal mode", f and f["mode"] == 1)
        check("all six sensor channels present",
              f and all(SLOT[k] in f["ch"] for k in ("MAG", "IMU", "THM", "PWR", "RAD", "STR")),
              str(sorted(f["ch"]. keys()) if f else None))
        check("AUX channel present (0x5A)", f and 0x5A in f["ch"])
        base_load = f["load_mw"] if f else 0
        check("bus load plausible", f and 700 <= base_load <= 1100, str(base_load))

        print("== 2. command protocol ==")
        check("PING", p.cmd("PING") == "ACK PING")
        check("NOOP", p.cmd("NOOP") == "ACK NOOP")
        r = p.cmd("STAT")
        check("STAT", r and r.startswith("ACK STAT mode=1") and "reboots=0" in r, r)
        check("bad CRC -> E01", p.raw("PING *0000") == "NAK E01")
        check("unknown verb -> E02", p.cmd("WARP 9") == "NAK E02")
        check("bad args -> E05", p.cmd("PEEK zz 4") == "NAK E05")

        print("== 3. introspection ==")
        r = p.cmd(f"PEEK 0x{SENS_BASE:08X} 16")
        check("PEEK sensor block", r and r.startswith("ACK PEEK ") and len(r) == 9 + 32, r)
        mag_ctrl = bytes.fromhex(r.split()[-1])[0] if r and r.startswith("ACK PEEK") else 0
        check("MAG powered (CTRL bit0)", mag_ctrl & 1)
        m1 = gdb_read_mem(SENS_BASE, 0x60)
        time.sleep(1.5)
        m2 = gdb_read_mem(SENS_BASE, 0x60)
        check("GDB stub reads sensor block", m1 is not None and m2 is not None)
        check("sensor registers are live (data changes)", m1 != m2)

        print("== 4. POKE protection ==")
        check("POKE ROM -> E04", p.cmd("POKE 0x00001000 00") == "NAK E04")
        check("POKE golden image -> E04", p.cmd("POKE 0x00004000 00") == "NAK E04")
        check("POKE NOINIT -> E04", p.cmd("POKE 0x20000000 00") == "NAK E04")
        check("POKE system block -> E04", p.cmd("POKE 0x20000104 00") == "NAK E04")
        check("POKE unmapped -> E03", p.cmd("POKE 0x40000000 00") == "NAK E03")

        print("== 5. objective 1: power down the magnetometer ==")
        r = p.cmd(f"POKE 0x{SENS_BASE:08X} 00000000")
        check("POKE MAG CTRL", r == "ACK POKE 4", r)
        f = None
        for _ in range(3):                    # allow one in-flight frame
            f = next_tlm(p)
            if f and SLOT["MAG"] not in f["ch"]:
                break
        check("MAG channel vanished", f and SLOT["MAG"] not in f["ch"],
              str(sorted(f["ch"].keys()) if f else None))
        check("bus load dropped >= 150 mW", f and base_load - f["load_mw"] >= 150,
              f"{base_load} -> {f['load_mw'] if f else '?'}")

        print("== 6. camera ==")
        r = p.cmd(f"POKE 0x{CAM_BASE:08X} 03")     # CAPTURE_NOW | AUTO
        check("trigger capture", r == "ACK POKE 1", r)
        time.sleep(2.5)
        r = p.cmd(f"PEEK 0x{CAM_BASE + 0x14:08X} 4")
        fid = int.from_bytes(bytes.fromhex(r.split()[-1]), "little") if r and "PEEK" in r else 0
        check("frame captured (FRAME_ID > 0)", fid > 0, r)
        f = next_tlm(p)
        check("camera channel 0x43 in telemetry", f and 0x43 in f["ch"])
        stats1 = f["ch"].get(0x43, b"") if f else b""
        sat1 = int.from_bytes(stats1[8:10], "big") if len(stats1) >= 12 else -1
        stars1 = int.from_bytes(stats1[10:12], "big") if len(stats1) >= 12 else -1
        # gross overexposure: exposure 8000 ms (little-endian u32 at +0x0C)
        p.cmd(f"POKE 0x{CAM_BASE + 0x0C:08X} 401F0000")
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        f = next_tlm(p)
        stats2 = f["ch"].get(0x43, b"") if f else b""
        sat2 = int.from_bytes(stats2[8:10], "big") if len(stats2) >= 12 else -1
        stars2 = int.from_bytes(stats2[10:12], "big") if len(stats2) >= 12 else -1
        check("overexposure raises SAT_PCT", sat2 > sat1, f"{sat1} -> {sat2}")
        check("overexposure washes out stars", stars2 < stars1, f"{stars1} -> {stars2}")

        print("== 6a. imaging pipeline (stored scenes, LUT, retarget) ==")
        lut = int(symbols["cam_lut"], 16)
        egg = int(symbols["g_cam_egg_pct"], 16)
        check("scene store lives outside the player binary",
              int(symbols["scene_store"], 16) < 0x20000000,
              symbols["scene_store"])
        p.cmd(f"POKE 0x{egg:08X} 00")        # deterministic imaging checks
        fb = 0x20020000
        # restore a sane exposure after the overexposure check above
        p.cmd(f"POKE 0x{CAM_BASE + 0x0C:08X} FA000000")      # 250 ms
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        base_px = bytes.fromhex(p.cmd(f"PEEK 0x{fb:08X} 32").split()[-1])
        check("frame buffer holds scene pixels", any(b > 0 for b in base_px),
              base_px.hex())
        f = next_tlm(p)
        cam = f["ch"].get(0x43, b"") if f else b""
        mean_before = int.from_bytes(cam[6:8], "big") if len(cam) >= 12 else -1
        check("nominal frame is mostly dark sky", 0 <= mean_before < 90,
              str(mean_before))

        # Invert purely as a data patch: rewrite the 256-byte transfer curve.
        inv = bytes(255 - i for i in range(256))
        for off in range(0, 256, 32):
            r = p.cmd(f"POKE 0x{lut + off:08X} {inv[off:off+32].hex().upper()}")
            if r != "ACK POKE 32":
                break
        check("inverting LUT installed (8 uplinks)", r == "ACK POKE 32", r)
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        inv_px = bytes.fromhex(p.cmd(f"PEEK 0x{fb:08X} 32").split()[-1])
        check("downlinked pixels are inverted",
              all(a + b == 255 for a, b in zip(base_px, inv_px)),
              f"{base_px[:6].hex()} vs {inv_px[:6].hex()}")
        f = next_tlm(p)
        cam = f["ch"].get(0x43, b"") if f else b""
        mean_after = int.from_bytes(cam[6:8], "big") if len(cam) >= 12 else -1
        check("inversion is visible in telemetry alone", mean_after > 150,
              f"mean {mean_before} -> {mean_after}")

        # Retarget: a different catalog entry returns a different scene.
        for off in range(0, 256, 32):                        # restore identity
            p.cmd(f"POKE 0x{lut + off:08X} {bytes(range(off, off+32)).hex().upper()}")
        p.cmd(f"POKE 0x{CAM_BASE + 0x08:08X} 03000000")      # target 3
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        t3_px = bytes.fromhex(p.cmd(f"PEEK 0x{fb + 2048:08X} 32").split()[-1])
        p.cmd(f"POKE 0x{CAM_BASE + 0x08:08X} 00000000")      # back to target 0
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        t0_px = bytes.fromhex(p.cmd(f"PEEK 0x{fb + 2048:08X} 32").split()[-1])
        check("retargeting returns a different scene", t3_px != t0_px,
              f"{t3_px[:6].hex()} vs {t0_px[:6].hex()}")

        # The easter egg: forcing the rate to 100% must return a scene the
        # catalog cannot command, proving it exists and is reachable.
        p.cmd(f"POKE 0x{egg:08X} 64")
        p.cmd(f"POKE 0x{CAM_BASE:08X} 03")
        time.sleep(2.5)
        egg_px = bytes.fromhex(p.cmd(f"PEEK 0x{fb + 2048:08X} 32").split()[-1])
        check("easter egg returns an uncommandable scene", egg_px != t0_px,
              f"{egg_px[:6].hex()} vs {t0_px[:6].hex()}")
        p.cmd(f"POKE 0x{egg:08X} 00")

        # Bulk downlink ships disabled: the verb exists but announces itself
        # as a capability to be restored, not an unknown command.
        dump_gate = int(symbols["g_dump_enable"], 16)
        check("DUMP exists but is disabled as built",
              p.cmd(f"DUMP 0x{fb:08X} 64") == "NAK E08")
        p.cmd(f"POKE 0x{dump_gate:08X} 01")
        r = p.cmd(f"DUMP 0x{fb:08X} 256")
        check("DUMP works once the gate is patched on",
              r and r.startswith("ACK DUMP ") and len(r.split()[-1]) == 512,
              (r or "")[:40])
        peeked = bytes.fromhex(p.cmd(f"PEEK 0x{fb:08X} 64").split()[-1])
        check("DUMP bytes agree with PEEK",
              r.split()[-1].upper().startswith(peeked.hex().upper()))
        p.cmd(f"POKE 0x{dump_gate:08X} 00")

        print("== 6b. auxiliary flight functions ==")
        f = next_tlm(p)
        hk = f["ch"].get(0x60, b"") if f else b""
        check("housekeeping channel 0x60 present", len(hk) == 8, str(len(hk)))
        if len(hk) == 8:
            heater_on = hk[0]
            shed_count = hk[1]
            propellant = int.from_bytes(hk[2:4], "big")
            rec_pct = hk[6]
            auth = hk[7]
            check("heater off as built", heater_on == 0, str(heater_on))
            check("no autonomous load shedding as built", shed_count == 0, str(shed_count))
            check("propellant loaded (~8000 mg)", 6000 <= propellant <= 8000, str(propellant))
            check("recorder buffer not overflowing", rec_pct < 100, str(rec_pct))
            check("engineering commands locked by default", auth == 0, str(auth))
        check("privileged TRIM rejected without auth", p.cmd("TRIM") == "NAK E07")
        check("AUTH with wrong key rejected", p.cmd("AUTH 00000000") == "NAK E07")
        check("AUTH with correct key accepted", p.cmd("AUTH 5A3C96E1") == "ACK AUTH")
        check("TRIM accepted once authorized", p.cmd("TRIM") == "ACK TRIM")
        f = next_tlm(p)
        hk = f["ch"].get(0x60, b"") if f else b""
        check("auth flag set in telemetry", len(hk) == 8 and hk[7] == 1,
              str(hk[7] if len(hk) == 8 else None))

        print("== 6c. trampoline patch (detour out and return) ==")
        # The scenario a real mission faces: change a function that has no
        # room for the new code. Overwrite its 8-byte entry pad with a jump
        # into the code cave, run new instructions there, then jump back to
        # <func>+8 so the original body still executes. Nothing is relocated,
        # because only NOP padding is overwritten.
        task_acs = int(symbols["task_acs"], 16)
        shed_addr = int(symbols["g_shed_count"], 16)
        cave = 0x2001D000                       # PATCH_SLOT(0)
        ret = (task_acs + 8) | 1                # back into the real body
        SENTINEL = 42

        hook = bytes([
            0x02, 0x48,                         # LDR  R0,[PC,#8]  -> &g_shed_count
            SENTINEL, 0x21,                     # MOVS R1,#42
            0x01, 0x70,                         # STRB R1,[R0]
            0x02, 0x4A,                         # LDR  R2,[PC,#8]  -> return addr
            0x10, 0x47,                         # BX   R2
            0x00, 0xBF,                         # NOP (align literals)
        ]) + shed_addr.to_bytes(4, "little") + ret.to_bytes(4, "little")

        r = p.cmd(f"POKE 0x{cave:08X} {hook.hex().upper()}")
        check("write hook into code cave", r == f"ACK POKE {len(hook)}", r)
        r = p.cmd(f"PEEK 0x{cave:08X} {len(hook)}")
        check("hook reads back intact",
              r and r.split()[-1].upper() == hook.hex().upper(), r)

        f = next_tlm(p)
        hk_before = f["ch"].get(0x60, b"") if f else b""
        mom_before = int.from_bytes(hk_before[4:6], "big", signed=True) if len(hk_before) == 8 else 0
        reboots_before = f["reboots"] if f else -1

        detour = bytes([0xDF, 0xF8, 0x00, 0xF0]) + (cave | 1).to_bytes(4, "little")
        r = p.cmd(f"POKE 0x{task_acs:08X} {detour.hex().upper()}")
        check("detour written over the entry pad", r == "ACK POKE 8", r)

        time.sleep(3)
        f = next_tlm(p)
        hk_after = f["ch"].get(0x60, b"") if f else b""
        if len(hk_after) == 8:
            check("hook executed (sentinel in telemetry)", hk_after[1] == SENTINEL,
                  f"shed_count={hk_after[1]}, expected {SENTINEL}")
            mom_after = int.from_bytes(hk_after[4:6], "big", signed=True)
            check("returned into original function (momentum still advancing)",
                  mom_after > mom_before, f"{mom_before} -> {mom_after}")
        else:
            check("hook executed (sentinel in telemetry)", False, "no HK channel")
            check("returned into original function (momentum still advancing)", False, "no HK")
        check("probe did not fault (no reboot)", f and f["reboots"] == reboots_before,
              f"reboots {reboots_before} -> {f['reboots'] if f else '?'}")
        check("probe still responsive after patch", p.cmd("PING") == "ACK PING")

        print("== 7. brick and recover (watchdog) ==")
        wdg_flags = task_table + 3 * 16 + 12      # entry 3 = wdg_pet, flags @ +12
        r = p.cmd(f"POKE 0x{wdg_flags:08X} 00")
        check("disable wdg_pet task", r == "ACK POKE 1", r)
        banner = p.wait_for(lambda l: "SOJOURN FSW" in l, 15)
        check("watchdog rebooted the probe", banner is not None, "no reboot banner")
        check("reboot counter incremented", banner and "reboots=1" in banner, banner)
        check("fault code = WDG(1)", banner and "fault=1" in banner, banner)
        f = next_tlm(p)
        check("uptime reset", f and f["uptime"] <= 10, str(f["uptime"] if f else None))
        check("golden image restored (MAG channel back)", f and SLOT["MAG"] in f["ch"])
        r = p.cmd("STAT")
        check("post-recovery STAT", r and "reboots=1" in r and "mode=1" in r, r)

        print(f"\n{passed} passed, {failed} failed")
        return 1 if failed else 0
    finally:
        qemu.kill()

if __name__ == "__main__":
    sys.exit(main())
