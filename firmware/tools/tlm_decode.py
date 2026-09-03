#!/usr/bin/env python3
"""tlm_decode.py — Sojourn ground-side telemetry receiver & decoder.

The reference implementation of the downlink format (Firmware Design
Specification §9).  The capstone team's game daemon should decode frames
exactly the way this file does.

Frame (hex-encoded on a "TLM " line):

    SYNC(2)=0xEB90  LEN(1)  payload  CRC16(2)

    payload: FRAME_CNT(2) UPTIME(4) MODE(1) REBOOTS(1) LAST_FAULT(1)
             BUS_MV(2) LOAD_MW(2)  then TLV channels {ID(1) LEN(1) VALUE}

    LEN     = payload byte count
    CRC     = CRC-16/CCITT-FALSE over LEN + payload
    values  = big-endian; sensor channel VALUEs are signed 32-bit

Channels: 0x00 MAG · 0x01 IMU · 0x02 THM · 0x03 PWR · 0x04 RAD ·
          0x05 STR · 0x43 CAM metadata · 0x5A AUX.
A powered-down or unpolled sensor's channel is ABSENT (not zero) — the
decoder flags appearance/disappearance as events.

Usage:
    tlm_decode.py --spawn [ROM_ELF]        boot QEMU and decode live
    tlm_decode.py --connect HOST:PORT      attach to a running probe
                                           (e.g. make run-tcp -> :5599)
    tlm_decode.py --file capture.txt       decode a captured log
    tlm_decode.py                          decode stdin
Options:
    --json      one JSON object per frame on stdout (machine-readable)
    --raw       echo non-telemetry lines (banner, ACK/NAK) verbatim
"""
import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

FIRMWARE = Path(__file__).resolve().parent.parent

MODES = {0: "BOOT", 1: "NOMINAL", 2: "SAFE"}
FAULTS = {0: "-", 1: "WDG", 2: "HARD", 3: "BADIMG"}
SENSOR_CH = {0: "MAG", 1: "IMU", 2: "THM", 3: "PWR", 4: "RAD", 5: "STR"}
CH_CAM, CH_HK, CH_COMMS, CH_AUX = 0x43, 0x60, 0x61, 0x5A
ANTENNA = {0: 'HGA', 1: 'LGA'}


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def s32(b: bytes) -> int:
    return int.from_bytes(b, "big", signed=True)


def decode_frame(hexstr: str):
    """Decode one TLM hex payload -> dict, or raise ValueError."""
    raw = bytes.fromhex(hexstr)
    if len(raw) < 18:
        raise ValueError("frame too short")
    if raw[0] != 0xEB or raw[1] != 0x90:
        raise ValueError("bad sync")
    paylen = raw[2]
    if len(raw) != 3 + paylen + 2:
        raise ValueError(f"length mismatch (LEN={paylen}, have {len(raw) - 5})")
    payload = raw[3:3 + paylen]
    want = int.from_bytes(raw[3 + paylen:], "big")
    got = crc16_ccitt(raw[2:3 + paylen])
    frame = {
        "crc_ok": got == want,
        "frame": int.from_bytes(payload[0:2], "big"),
        "uptime_s": int.from_bytes(payload[2:6], "big"),
        "mode": MODES.get(payload[6], f"?{payload[6]}"),
        "reboots": payload[7],
        "last_fault": FAULTS.get(payload[8], f"?{payload[8]}"),
        "bus_mv": int.from_bytes(payload[9:11], "big"),
        "load_mw": int.from_bytes(payload[11:13], "big"),
        "channels": {},
    }
    i = 13
    while i + 2 <= len(payload):
        cid, clen = payload[i], payload[i + 1]
        val = payload[i + 2:i + 2 + clen]
        i += 2 + clen
        if cid in SENSOR_CH and clen == 4:
            frame["channels"][SENSOR_CH[cid]] = s32(val)
        elif cid == CH_CAM and clen == 12:
            u16 = lambda o: int.from_bytes(val[o:o + 2], "big")
            frame["channels"]["CAM"] = {
                "frame_id": u16(0), "target": u16(2), "exposure_ms": u16(4),
                "hist_mean": u16(6), "sat_pct": u16(8), "stars": u16(10),
            }
        elif cid == CH_HK and clen == 8:
            frame["channels"]["HK"] = {
                "heater_on": val[0],
                "shed_count": val[1],
                "propellant_mg": int.from_bytes(val[2:4], "big"),
                "momentum": int.from_bytes(val[4:6], "big", signed=True),
                "rec_fill_pct": val[6],
                "auth": val[7],
            }
        elif cid == CH_COMMS and clen == 4:
            frame["channels"]["COMMS"] = {
                "antenna": ANTENNA.get(val[0], f"?{val[0]}"),
                "dropped": val[1],
                "budget": int.from_bytes(val[2:4], "big"),
            }
        elif cid == CH_AUX and clen == 2:
            frame["channels"]["AUX"] = f"0x{int.from_bytes(val, 'big'):04X}"
        else:
            frame["channels"][f"0x{cid:02X}"] = val.hex().upper()
    return frame


# ---------------- pretty printing & event detection ----------------
def fmt_sensor(name, v):
    if name == "MAG":
        return f"MAG {v:>6} nT"
    if name == "IMU":
        return f"IMU {v / 100:>6.2f} °/s"
    if name == "THM":
        return f"THM {v / 10:>5.1f} °C"
    if name == "PWR":
        return f"PWR {v:>5} mV"
    if name == "RAD":
        return f"RAD {v:>5} ct"
    if name == "STR":
        return f"STR q={v / 10000:.4f}"
    return f"{name}={v}"


class Printer:
    def __init__(self, as_json):
        self.as_json = as_json
        self.prev = None

    def events(self, f):
        ev = []
        p = self.prev
        if p:
            for name in SENSOR_CH.values():
                if name in p["channels"] and name not in f["channels"]:
                    ev.append(f"channel {name} LOST")
                if name not in p["channels"] and name in f["channels"]:
                    ev.append(f"channel {name} ACQUIRED")
            if f["reboots"] != p["reboots"]:
                ev.append(f"PROBE REBOOTED ({p['reboots']} -> {f['reboots']}, "
                          f"fault={f['last_fault']})")
            if f["mode"] != p["mode"]:
                ev.append(f"mode {p['mode']} -> {f['mode']}")
            c1, c2 = p["channels"].get("CAM"), f["channels"].get("CAM")
            if c2 and (not c1 or c2["frame_id"] != c1["frame_id"]):
                ev.append(f"CAM capture #{c2['frame_id']}: target={c2['target']} "
                          f"exp={c2['exposure_ms']}ms mean={c2['hist_mean']} "
                          f"sat={c2['sat_pct']}% stars={c2['stars']}")
            k1, k2 = p["channels"].get("COMMS"), f["channels"].get("COMMS")
            if k1 and k2:
                if k2["antenna"] != k1["antenna"]:
                    ev.append(f"ANTENNA {k1['antenna']} -> {k2['antenna']} "
                              f"(budget {k1['budget']} -> {k2['budget']} bytes)")
                if k2["dropped"] and not k1["dropped"]:
                    ev.append(f"DOWNLINK SATURATED: {k2['dropped']} channels dropped")
                elif k2["dropped"] != k1["dropped"]:
                    ev.append(f"dropped channels {k1['dropped']} -> {k2['dropped']}")
            h1, h2 = p["channels"].get("HK"), f["channels"].get("HK")
            if h1 and h2:
                if h2["shed_count"] != h1["shed_count"]:
                    ev.append(f"POWER LOAD SHED (count {h1['shed_count']} -> {h2['shed_count']})")
                if h2["auth"] and not h1["auth"]:
                    ev.append("ENGINEERING COMMAND UNLOCKED (auth)")
                if h2["heater_on"] != h1["heater_on"]:
                    ev.append("heater ON" if h2["heater_on"] else "heater OFF")
                if h2["rec_fill_pct"] >= 100 and h1["rec_fill_pct"] < 100:
                    ev.append("RECORDER BUFFER FULL")
        self.prev = f
        return ev

    def show(self, f):
        ev = self.events(f)
        if self.as_json:
            f2 = dict(f)
            f2["events"] = ev
            print(json.dumps(f2), flush=True)
            return
        if not f["crc_ok"]:
            print(f"[{f['frame']:04d}] *** BAD CRC ***", flush=True)
            return
        head = (f"[{f['frame']:04d}] up={f['uptime_s']:>6}s {f['mode']:<7} "
                f"reboots={f['reboots']} fault={f['last_fault']:<6} "
                f"bus={f['bus_mv'] / 1000:.3f}V load={f['load_mw']}mW")
        sensors = [fmt_sensor(n, v) for n, v in f["channels"].items()
                   if n in SENSOR_CH.values()]
        aux = f["channels"].get("AUX")
        line2 = " | ".join(sensors) + (f" | AUX {aux}" if aux else "")
        print(head, flush=True)
        if line2:
            print(f"       {line2}", flush=True)
        cm = f["channels"].get("COMMS")
        if cm:
            print(f"       LINK {cm['antenna']} | budget={cm['budget']}B | "
                  f"dropped={cm['dropped']}", flush=True)
        hk = f["channels"].get("HK")
        if hk:
            print(f"       HK  heater={'on' if hk['heater_on'] else 'off'} | "
                  f"prop={hk['propellant_mg']}mg | mom={hk['momentum']} | "
                  f"rec={hk['rec_fill_pct']}% | shed={hk['shed_count']} | "
                  f"auth={'YES' if hk['auth'] else 'no'}", flush=True)
        for e in ev:
            print(f"     ! {e}", flush=True)


# ---------------- input sources ----------------
def lines_from_socket(hostport):
    host, port = hostport.rsplit(":", 1)
    deadline = time.time() + 15
    sock = None
    while time.time() < deadline and sock is None:
        try:
            sock = socket.create_connection((host, int(port)), 2)
        except OSError:
            time.sleep(0.3)
    if sock is None:
        sys.exit(f"cannot connect to {hostport}")
    buf = b""
    sock.settimeout(1.0)
    while True:
        if b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            yield line.decode(errors="replace").strip()
            continue
        try:
            d = sock.recv(4096)
            if not d:
                return
            buf += d
        except socket.timeout:
            pass


def lines_from_spawn(rom_elf):
    qemu = subprocess.Popen(
        ["qemu-system-arm", "-M", "mps2-an386", "-nographic", "-monitor", "none",
         "-kernel", str(rom_elf), "-serial", "stdio"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        for line in qemu.stdout:
            yield line.strip()
    finally:
        qemu.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--spawn", nargs="?", const=str(FIRMWARE / "build" / "probe_rom.elf"),
                     metavar="ROM_ELF", help="boot QEMU and decode its downlink live")
    src.add_argument("--connect", metavar="HOST:PORT",
                     help="attach to a running probe's serial TCP port")
    src.add_argument("--file", metavar="PATH", help="decode a captured log file")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--raw", action="store_true", help="echo non-telemetry lines")
    args = ap.parse_args()

    if args.spawn:
        lines = lines_from_spawn(args.spawn)
    elif args.connect:
        lines = lines_from_socket(args.connect)
    elif args.file:
        lines = (l.strip() for l in open(args.file, errors="replace"))
    else:
        lines = (l.strip() for l in sys.stdin)

    printer = Printer(args.json)
    bad = 0
    try:
        for line in lines:
            if line.startswith("TLM "):
                try:
                    printer.show(decode_frame(line[4:]))
                except ValueError as e:
                    bad += 1
                    print(f"  ?? undecodable frame: {e}", file=sys.stderr, flush=True)
            elif line and args.raw:
                print(f"  >> {line}", flush=True)
    except KeyboardInterrupt:
        pass
    except BrokenPipeError:                    # e.g. piped into head
        sys.stderr.close()
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
