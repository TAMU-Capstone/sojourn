#!/usr/bin/env python3
"""scenario_eval.py — REFERENCE EVALUATOR for the Sojourn scenario format.

This is an ORACLE, not a daemon. It exists for exactly two reasons:

  1. to prove the assertion vocabulary in the Scenario Package Format
     specification is sufficient to express the reference scenarios, and
  2. to generate the expected outputs in conformance/, from real firmware
     runs rather than from someone's belief about what should happen.

It stands to the format spec as tools/tlm_decode.py stands to the telemetry
section: where this program and the specification disagree, one of them is a
bug, and they are fixed together.

It is deliberately NOT a starting point for the game daemon. It has no
scenario discovery, no transmission-delay simulation, no persistence, no
player profiles, no console and no HTTP surface -- which is to say it does
none of the things the daemon exists to do. A team that grows this file into
their daemon will have inherited a test harness's architecture.

Usage:
    scenario_eval.py --scenario DIR [--replay LOG] [--out state.json]
    scenario_eval.py --scenario DIR --script moves.txt --record LOG

    --replay    apply an existing command log (the conformance path)
    --script    apply a plain-text move list, one uplink per line, and write
                the resulting log with --record (the authoring path)
    --frames N  stop after N downlink frames (default: from the scenario)
    --verbose   print per-frame objective transitions as they happen
"""
import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tlm_decode as T                                          # noqa: E402

QEMU = os.environ.get("QEMU_BIN", "qemu-system-arm")
SER_PORT = int(os.environ.get("SCEN_SER_PORT", "5601"))
GDB_PORT = int(os.environ.get("SCEN_GDB_PORT", "3401"))


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


# --------------------------------------------------------------------------
# probe transport: uplink commands and downlink frames over the emulated UART
# --------------------------------------------------------------------------
class Probe:
    """A running probe. Uplinks are text; downlinks are TLM lines."""

    def __init__(self, rom_elf):
        self.proc = subprocess.Popen(
            [QEMU, "-M", "mps2-an386", "-nographic", "-monitor", "none",
             "-kernel", str(rom_elf),
             "-serial", f"tcp:127.0.0.1:{SER_PORT},server=on,wait=on",
             "-gdb", f"tcp::{GDB_PORT}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.buf = b""
        self.pending_frames = []      # frames seen while awaiting a command reply
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                self.sock = socket.create_connection(("127.0.0.1", SER_PORT), 1)
                self.sock.settimeout(0.2)
                break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("probe did not come up")

    def readline(self, timeout=15.0):
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

    def uplink(self, text, timeout=6.0, checksum=True):
        """Send one command, return the probe's reply (skipping TLM lines).

        The probe requires the CRC-16 suffix the manual documents; without it
        the command is rejected E01 before the verb is even looked at.
        """
        full = f"{text} *{crc16_ccitt(text.encode() + b' '):04X}" if checksum else text
        self.sock.sendall((full + "\r\n").encode())
        end = time.time() + timeout
        while time.time() < end:
            line = self.readline(min(2.0, max(0.1, end - time.time())))
            if line is None:
                continue
            if line.startswith("TLM "):
                self.pending_frames.append(line)
                continue
            if line.startswith(("ACK", "NAK")):
                return line
        return "TIMEOUT"

    def next_frame(self, timeout=20.0):
        if self.pending_frames:
            return self.pending_frames.pop(0)
        end = time.time() + timeout
        while time.time() < end:
            line = self.readline(min(2.0, max(0.1, end - time.time())))
            if line and line.startswith("TLM "):
                return line
        return None

    def read_mem(self, addr, length):
        """Read memory the way the ground does: PEEK, 64 bytes at a time.

        The evaluator uses the player's own read path rather than a debugger
        backdoor, so a package cannot assert against state the ground could
        not itself observe.
        """
        out = b""
        while len(out) < length:
            n = min(64, length - len(out))
            reply = self.uplink(f"PEEK 0x{addr + len(out):08X} {n}")
            m = re.match(r"ACK PEEK ([0-9A-Fa-f]+)\s*$", reply or "")
            if not m:
                raise RuntimeError(f"PEEK failed at 0x{addr + len(out):08X}: {reply}")
            out += bytes.fromhex(m.group(1))
        return out[:length]

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
        self.proc.kill()
        self.proc.wait(timeout=5)


# --------------------------------------------------------------------------
# address resolution (format spec 6.3)
# --------------------------------------------------------------------------
class Symbols:
    def __init__(self, symbols_json, memmap_json):
        d = json.load(open(symbols_json))
        self.sym = {k: int(v, 16) for k, v in d["symbols"].items()}
        self.fields = d.get("fields", {})
        self.regions = [
            (int(r["lo"], 16), int(r["hi"], 16), r["name"])
            for r in json.load(open(memmap_json))["regions"]
        ]

    def resolve(self, at):
        if "addr" in at:
            return int(at["addr"], 16)
        name = at["sym"]
        if name not in self.sym:
            raise KeyError(f"unknown symbol {name!r}")
        base = self.sym[name]
        if "field" in at:
            fields = self.fields.get(name, {})
            if at["field"] not in fields:
                raise KeyError(f"{name} has no field {at['field']!r}")
            return base + fields[at["field"]]
        return base + int(at.get("offset", 0))

    def in_map(self, addr, length=1):
        return any(lo <= addr and addr + length <= hi for lo, hi, _ in self.regions)


# --------------------------------------------------------------------------
# predicate evaluation (format spec 6.2)
# --------------------------------------------------------------------------
CMP = {
    "eq":  lambda a, b: a == b,
    "ne":  lambda a, b: a != b,
    "lt":  lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt":  lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "in":  lambda a, b: a in b,
}

SENSOR_NAMES = set(T.SENSOR_CH.values())


class Context:
    """Everything a predicate may see. Nothing else is reachable."""

    def __init__(self, syms):
        self.syms = syms
        self.frame = None
        self.events = []
        self.history = []          # decoded frames, oldest first
        self.snapshot = {}         # (addr, len) -> bytes, this frame only
        self.baseline = {}         # (addr, len) -> bytes, after setup
        self.log = []
        self.budget = {"writes": 0, "reads": 0}
        self.probe = None

    def mem(self, addr, length):
        """Frame-boundary snapshot: repeated reads in one pass agree."""
        key = (addr, length)
        if key not in self.snapshot:
            self.snapshot[key] = self.probe.read_mem(addr, length)
        return self.snapshot[key]


def dotted(obj, path):
    for part in path.split("."):
        if isinstance(obj, dict) and part in obj:
            obj = obj[part]
        else:
            return None
    return obj


def evaluate(pred, ctx):
    """A predicate is a pure function of ctx. Missing data is False, never
    an error -- format spec section 7, 'Missing data is false'."""
    op = pred.get("op")

    # ---- combinators ----
    if op == "all":
        return all(evaluate(p, ctx) for p in pred["of"])
    if op == "any":
        return any(evaluate(p, ctx) for p in pred["of"])
    if op == "not":
        return not evaluate(pred["of"], ctx)
    if op == "ever":
        return ctx.latched.get(id(pred), False)
    if op in ("sustained", "within"):
        hits = ctx.streak.get(id(pred), [])
        n = int(pred["frames"])
        if op == "sustained":
            return len(hits) >= n and all(hits[-n:])
        return any(hits[-n:]) if hits else False

    # ---- telemetry ----
    if op == "tlm":
        val = dotted(ctx.frame, pred["path"]) if ctx.frame else None
        if val is None:
            return False
        return CMP[pred.get("cmp", "eq")](val, pred["value"])
    if op == "tlm_bits":
        val = dotted(ctx.frame, pred["path"]) if ctx.frame else None
        if val is None:
            return False
        return CMP[pred.get("cmp", "eq")](int(val) & int(pred["mask"]), pred["value"])
    if op == "channel_present":
        return bool(ctx.frame) and pred["id"] in ctx.frame.get("channels", {})
    if op == "channel_absent":
        return bool(ctx.frame) and pred["id"] not in ctx.frame.get("channels", {})
    if op == "event":
        if pred.get("regex"):
            rx = re.compile(pred["match"])
            return any(rx.search(e) for e in ctx.events)
        return any(pred["match"] in e for e in ctx.events)

    # ---- memory ----
    if op in ("mem_u8", "mem_u16", "mem_u32"):
        width = {"mem_u8": 1, "mem_u16": 2, "mem_u32": 4}[op]
        addr = ctx.syms.resolve(pred["at"])
        raw = ctx.mem(addr, width)
        val = int.from_bytes(raw, "little")
        return CMP[pred.get("cmp", "eq")](val, pred["value"])
    if op == "mem":
        addr = ctx.syms.resolve(pred["at"])
        raw = ctx.mem(addr, int(pred["len"]))
        return CMP[pred.get("cmp", "eq")](raw.hex().lower(),
                                          str(pred["value"]).lower())
    if op == "mem_bits":
        addr = ctx.syms.resolve(pred["at"])
        width = int(pred.get("width", 4))
        val = int.from_bytes(ctx.mem(addr, width), "little") & int(pred["mask"])
        return CMP[pred.get("cmp", "eq")](val, pred["value"])
    if op == "mem_changed":
        addr = ctx.syms.resolve(pred["at"])
        n = int(pred["len"])
        was = ctx.baseline.get((addr, n))
        if was is None:
            return False
        return ctx.mem(addr, n) != was

    # ---- command log ----
    if op == "commanded":
        want_verb = pred.get("verb")
        want_result = pred.get("result")
        want_addr = ctx.syms.resolve(pred["at"]) if "at" in pred else None
        for rec in ctx.log:
            if want_verb and rec.get("verb") != want_verb:
                continue
            if want_result and not str(rec.get("result", "")).startswith(want_result):
                continue
            if want_addr is not None:
                m = re.search(r"0[xX]([0-9A-Fa-f]+)", rec.get("raw", ""))
                if not m or int(m.group(1), 16) != want_addr:
                    continue
            return True
        return False
    if op == "budget":
        got = ctx.budget.get(pred["resource"], 0)
        return CMP[pred.get("cmp", "lte")](got, pred["value"])

    # ---- escape hatch (format spec 6.7) ----
    if op == "script":
        raise NotImplementedError(
            "the reference evaluator is pure-mode only and refuses "
            "script predicates; see format spec section 6.7")

    raise ValueError(f"unknown predicate op {op!r}")


def walk(pred):
    """Every predicate node, for latch/streak bookkeeping."""
    yield pred
    for key in ("of",):
        child = pred.get(key)
        if isinstance(child, list):
            for c in child:
                yield from walk(c)
        elif isinstance(child, dict):
            yield from walk(child)


def prime_temporal(pred, ctx):
    """Update `ever` latches and `sustained`/`within` streaks for this frame.

    Done depth-first before the objective is evaluated, so a temporal node's
    own state already reflects the current frame when its parent reads it.
    """
    for node in walk(pred):
        op = node.get("op")
        if op == "ever":
            if not ctx.latched.get(id(node)):
                ctx.latched[id(node)] = evaluate(node["of"], ctx)
        elif op in ("sustained", "within"):
            ctx.streak.setdefault(id(node), []).append(
                bool(evaluate(node["of"], ctx)))


# --------------------------------------------------------------------------
# the evaluation contract (format spec section 7)
# --------------------------------------------------------------------------
class Session:
    def __init__(self, pkg_dir, verbose=False):
        self.dir = Path(pkg_dir)
        self.manifest = json.load(open(self.dir / "manifest.json"))
        fw = self.manifest["firmware"]
        self.syms = Symbols(self.dir / fw["symbols"], self.dir / fw["memmap"])
        self.rom = self.dir / fw["rom"]
        self.objectives = json.load(
            open(self.dir / self.manifest["objectives"]))["objectives"]
        self.setup = None
        if self.manifest.get("setup"):
            self.setup = json.load(open(self.dir / self.manifest["setup"]))
        self.verbose = verbose
        self.state = {o["id"]: "locked" for o in self.objectives}
        self.first_frame = {o["id"]: None for o in self.objectives}
        self.partial = {o["id"]: None for o in self.objectives}

    # -- budget accounting (charter R4.2/R4.3: writes and reads metered apart)
    @staticmethod
    def charge_class(verb):
        if verb in ("POKE", "CALL", "TRIM", "SAFE"):
            return "writes"
        if verb in ("PEEK", "DUMP"):
            return "reads"
        return None

    def run(self, log_records=None, script=None, max_frames=None):
        probe = Probe(self.rom)
        ctx = Context(self.syms)
        ctx.probe = probe
        ctx.latched, ctx.streak = {}, {}
        try:
            probe.readline(20)                     # banner

            # ---- setup: initial conditions, not moves ----
            if self.setup:
                for w in self.setup.get("writes", []):
                    addr = self.syms.resolve(w["at"])
                    if "u32" in w:
                        payload = int(w["u32"]).to_bytes(4, "little").hex()
                    elif "u16" in w:
                        payload = int(w["u16"]).to_bytes(2, "little").hex()
                    elif "u8" in w:
                        payload = int(w["u8"]).to_bytes(1, "little").hex()
                    else:
                        payload = w["hex"]
                    probe.uplink(f"POKE 0x{addr:08X} {payload.upper()}")
                for _ in range(int(self.setup.get("settle_frames", 0))):
                    probe.next_frame()

            # ---- baseline for mem_changed, captured after setup ----
            for pred in self._all_predicates():
                if pred.get("op") == "mem_changed":
                    a = self.syms.resolve(pred["at"])
                    n = int(pred["len"])
                    ctx.baseline[(a, n)] = probe.read_mem(a, n)

            moves = list(log_records or [])
            if script:
                moves = [{"raw": line} for line in script]

            frames = 0
            limit = max_frames or (len(moves) + 12)
            move_i = 0
            printer_prev = None

            while frames < limit:
                # Apply any moves due before this frame. The reference
                # evaluator applies one move per frame, in order; a real
                # daemon schedules them by t_ms against transmission delay.
                if move_i < len(moves):
                    rec = moves[move_i]
                    move_i += 1
                    verb = rec.get("verb") or rec["raw"].split()[0].upper()
                    reply = probe.uplink(rec["raw"])
                    charged = self.charge_class(verb)
                    if charged:
                        ctx.budget[charged] = ctx.budget.get(charged, 0) + 1
                    ctx.log.append({
                        "seq": len(ctx.log) + 1,
                        "t_ms": None,
                        "raw": rec["raw"],
                        "verb": verb,
                        "charged": charged,
                        "result": reply,
                    })

                line = probe.next_frame()
                if line is None:
                    break
                try:
                    frame = T.decode_frame(line.split()[1])
                except (ValueError, IndexError):
                    continue
                if not frame.get("crc_ok"):
                    continue

                ctx.events = self._events(printer_prev, frame)
                printer_prev = frame
                ctx.frame = frame
                ctx.snapshot = {}                  # fresh per frame
                frames += 1

                self._evaluate_pass(ctx, frames)
                ctx.history.append(frame)

            self.log = ctx.log
            return self._result(frames, ctx)
        finally:
            probe.close()

    def _all_predicates(self):
        for o in self.objectives:
            for key in ("success", "fail"):
                if o.get(key):
                    yield from walk(o[key])
            for p in o.get("partial", []):
                yield from walk(p["when"])

    @staticmethod
    def _events(prev, frame):
        p = T.Printer(as_json=True)
        p.prev = prev
        return p.events(frame)

    def _evaluate_pass(self, ctx, frame_no):
        """Once per frame, objectives in declaration order, fail/partial/success."""
        for o in self.objectives:
            oid = o["id"]

            # gating on requires
            if self.state[oid] == "locked":
                deps = o.get("requires", [])
                if all(self.state[d] == "complete" for d in deps):
                    self.state[oid] = "active"
                else:
                    continue
            if self.state[oid] in ("complete", "failed") and not o.get("retractable"):
                continue

            for key in ("fail", "success"):
                if o.get(key):
                    prime_temporal(o[key], ctx)
            for p in o.get("partial", []):
                prime_temporal(p["when"], ctx)

            if o.get("fail") and evaluate(o["fail"], ctx):
                self._transition(oid, "failed", frame_no)
                continue
            for p in o.get("partial", []):
                if evaluate(p["when"], ctx):
                    self.partial[oid] = p["text"]
                    break
            else:
                self.partial[oid] = None
            if evaluate(o["success"], ctx):
                self._transition(oid, "complete", frame_no)

    def _transition(self, oid, state, frame_no):
        if self.state[oid] != state:
            self.state[oid] = state
            if self.first_frame[oid] is None:
                self.first_frame[oid] = frame_no
            if self.verbose:
                print(f"  frame {frame_no:>3}  {oid} -> {state}", flush=True)

    def _result(self, frames, ctx):
        return {
            "format": 1,
            "scenario": self.manifest["id"],
            "revision": self.manifest["revision"],
            "frames": frames,
            "objectives": [
                {"id": o["id"],
                 "state": self.state[o["id"]],
                 "first_frame": self.first_frame[o["id"]]}
                for o in self.objectives
            ],
            "budget": ctx.budget,
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    # The format spec's section 10 conformance entry point is
    #   <program> conform --scenario DIR --replay LOG --out FILE
    # Accepting it here means the reference evaluator satisfies the same
    # interface the daemon must, and the conformance runner can drive either.
    ap.add_argument("subcommand", nargs="?", choices=["conform"],
                    help=argparse.SUPPRESS)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--replay")
    ap.add_argument("--script")
    ap.add_argument("--record")
    ap.add_argument("--out")
    ap.add_argument("--frames", type=int)
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    records = script = None
    if a.replay:
        records = [json.loads(l) for l in open(a.replay) if l.strip()]
    if a.script:
        script = [l.strip() for l in open(a.script)
                  if l.strip() and not l.startswith("#")]

    s = Session(a.scenario, verbose=a.verbose)
    if a.verbose:
        print(f"scenario {s.manifest['id']} rev {s.manifest['revision']}", flush=True)
    result = s.run(log_records=records, script=script, max_frames=a.frames)

    text = json.dumps(result, indent=2)
    if a.out:
        Path(a.out).write_text(text + "\n")
        print(f"wrote {a.out}")
    else:
        print(text)

    if a.record:
        with open(a.record, "w") as f:
            for rec in s.log:
                f.write(json.dumps(rec) + "\n")
        print(f"wrote {a.record} ({len(s.log)} commands)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
