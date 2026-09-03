#!/usr/bin/env python3
"""scenario_validate.py — static validator for Sojourn scenario packages.

Implements the validation rules in the Scenario Package Format specification
(section 12) and satisfies charter R13: the three seeded-defect classes it
names — malformed manifest, unparsable assertion, and assertion address
outside the memory map — are rules V1, V4 and V6 below.

It reads the package only. It never starts a probe, so it is fast enough to
run on every save and in CI.

    scenario_validate.py PACKAGE_DIR [PACKAGE_DIR ...]
    scenario_validate.py --strict PACKAGE_DIR      # warnings fail too

Exit status is 0 when every package passes, 1 otherwise.
"""
import argparse
import json
import sys
from pathlib import Path

FORMAT = 1

REQUIRED_MANIFEST = ["format", "id", "title", "revision", "firmware",
                     "briefing", "objectives"]
REQUIRED_FIRMWARE = ["rom", "symbols", "memmap", "app_crc32"]

CMPS = {"eq", "ne", "lt", "lte", "gt", "gte", "in"}

# op -> (required keys, optional keys)
PREDICATES = {
    "all":             ({"of"}, set()),
    "any":             ({"of"}, set()),
    "not":             ({"of"}, set()),
    "ever":            ({"of"}, set()),
    "sustained":       ({"of", "frames"}, set()),
    "within":          ({"of", "frames"}, set()),
    "tlm":             ({"path", "value"}, {"cmp"}),
    "tlm_bits":        ({"path", "mask", "value"}, {"cmp"}),
    "channel_present": ({"id"}, set()),
    "channel_absent":  ({"id"}, set()),
    "event":           ({"match"}, {"regex"}),
    "mem_u8":          ({"at", "value"}, {"cmp"}),
    "mem_u16":         ({"at", "value"}, {"cmp"}),
    "mem_u32":         ({"at", "value"}, {"cmp"}),
    "mem":             ({"at", "len", "value"}, {"cmp"}),
    "mem_bits":        ({"at", "mask", "value"}, {"cmp", "width"}),
    "mem_changed":     ({"at", "len"}, set()),
    "commanded":       (set(), {"verb", "at", "result"}),
    "budget":          ({"resource", "value"}, {"cmp"}),
    "script":          ({"lang", "entry"}, set()),
}

WIDTH = {"mem_u8": 1, "mem_u16": 2, "mem_u32": 4}


class Report:
    def __init__(self, name):
        self.name, self.errors, self.warnings = name, [], []

    def err(self, rule, msg):
        self.errors.append(f"[{rule}] {msg}")

    def warn(self, msg):
        self.warnings.append(msg)

    def ok(self):
        return not self.errors


class Package:
    def __init__(self, path, rep):
        self.dir = Path(path)
        self.rep = rep
        self.manifest = {}
        self.symbols = {}
        self.fields = {}
        self.regions = []
        self.objectives = []


def load_json(pkg, rel, rule, what):
    p = pkg.dir / rel
    if not p.exists():
        pkg.rep.err(rule, f"{what}: file not found: {rel}")
        return None
    try:
        return json.load(open(p))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        pkg.rep.err(rule, f"{what}: unparsable JSON in {rel}: {e}")
        return None


# ---------------------------------------------------------------- addresses
def resolve(pkg, at, where):
    """Resolve an address reference, or None having reported why not."""
    if not isinstance(at, dict):
        pkg.rep.err("V4", f"{where}: 'at' must be an object")
        return None
    if "addr" in at:
        try:
            return int(str(at["addr"]), 16)
        except ValueError:
            pkg.rep.err("V4", f"{where}: 'addr' is not hexadecimal: {at['addr']!r}")
            return None
    if "sym" not in at:
        pkg.rep.err("V4", f"{where}: 'at' needs 'sym' or 'addr'")
        return None
    name = at["sym"]
    if name not in pkg.symbols:
        pkg.rep.err("V5", f"{where}: unknown symbol {name!r}")
        return None
    base = pkg.symbols[name]
    if "field" in at:
        fields = pkg.fields.get(name, {})
        if at["field"] not in fields:
            pkg.rep.err("V5", f"{where}: {name} has no field {at['field']!r}")
            return None
        return base + fields[at["field"]]
    off = at.get("offset", 0)
    if not isinstance(off, int):
        pkg.rep.err("V4", f"{where}: 'offset' must be an integer")
        return None
    return base + off


def check_in_map(pkg, addr, length, where):
    if any(lo <= addr and addr + length <= hi for lo, hi, _ in pkg.regions):
        return
    pkg.rep.err("V6", f"{where}: [0x{addr:08X}, +{length}) is outside every "
                      f"region in memmap.json")


# --------------------------------------------------------------- predicates
def check_predicate(pkg, pred, where):
    if not isinstance(pred, dict):
        pkg.rep.err("V4", f"{where}: predicate must be an object")
        return
    op = pred.get("op")
    if op not in PREDICATES:
        pkg.rep.err("V4", f"{where}: unknown predicate op {op!r}")
        return
    required, optional = PREDICATES[op]
    missing = required - set(pred)
    if missing:
        pkg.rep.err("V4", f"{where}: {op} missing {sorted(missing)}")
        return
    unknown = set(pred) - required - optional - {"op"}
    if unknown:
        pkg.rep.warn(f"{where}: {op} has unrecognised keys {sorted(unknown)}")

    if "cmp" in pred and pred["cmp"] not in CMPS:
        pkg.rep.err("V4", f"{where}: unknown comparison {pred['cmp']!r}")

    # V9: value type must suit the operator
    if op.startswith("mem_") and op != "mem_changed" and op != "mem":
        if not isinstance(pred.get("value"), int) and pred.get("cmp") != "in":
            pkg.rep.err("V9", f"{where}: {op} expects an integer 'value'")
    if op == "mem" and not isinstance(pred.get("value"), str):
        pkg.rep.err("V9", f"{where}: mem expects a hex-string 'value'")
    if op in ("sustained", "within"):
        if not isinstance(pred.get("frames"), int) or pred["frames"] < 1:
            pkg.rep.err("V9", f"{where}: {op} needs a positive integer 'frames'")
    if pred.get("cmp") == "in" and not isinstance(pred.get("value"), list):
        pkg.rep.err("V9", f"{where}: 'in' expects a list 'value'")
    if op == "budget" and pred.get("resource") not in ("writes", "reads"):
        pkg.rep.err("V9", f"{where}: budget resource must be 'writes' or 'reads'")

    # V6: address bounds
    if "at" in pred:
        addr = resolve(pkg, pred["at"], where)
        if addr is not None:
            if op == "mem_changed" or op == "mem":
                n = pred.get("len")
                n = n if isinstance(n, int) else 1
            elif op == "mem_bits":
                n = pred.get("width", 4)
            else:
                n = WIDTH.get(op, 1)
            check_in_map(pkg, addr, n, where)

    if op == "script":
        entry = str(pred.get("entry", ""))
        rel = entry.split(":")[0]
        if not (pkg.dir / rel).exists():
            pkg.rep.err("V3", f"{where}: script entry file not found: {rel}")

    # recurse
    child = pred.get("of")
    if isinstance(child, list):
        for i, c in enumerate(child):
            check_predicate(pkg, c, f"{where}.of[{i}]")
    elif isinstance(child, dict):
        check_predicate(pkg, child, f"{where}.of")
    elif "of" in PREDICATES[op][0]:
        pkg.rep.err("V4", f"{where}: {op} 'of' must be an object or a list")


# --------------------------------------------------------------- the checks
def validate(path, strict=False):
    rep = Report(str(path))
    pkg = Package(path, rep)

    if not pkg.dir.is_dir():
        rep.err("V1", "not a directory")
        return rep

    # ---- V1/V2: manifest ----
    man = load_json(pkg, "manifest.json", "V1", "manifest")
    if man is None:
        return rep
    pkg.manifest = man
    for k in REQUIRED_MANIFEST:
        if k not in man:
            rep.err("V1", f"manifest missing required key {k!r}")
    if not isinstance(man.get("format"), int):
        rep.err("V1", "manifest 'format' must be an integer")
    elif man["format"] > FORMAT:
        rep.err("V2", f"manifest format {man['format']} is newer than this "
                      f"validator understands ({FORMAT})")
    if not isinstance(man.get("revision"), int):
        rep.err("V1", "manifest 'revision' must be an integer")
    fw = man.get("firmware")
    if not isinstance(fw, dict):
        rep.err("V1", "manifest 'firmware' must be an object")
        return rep
    for k in REQUIRED_FIRMWARE:
        if k not in fw:
            rep.err("V1", f"manifest firmware missing {k!r}")
    if rep.errors:
        return rep

    known = set(REQUIRED_MANIFEST) | {"author", "summary", "difficulty", "link",
                                      "setup", "docs", "impure"}
    for k in man:
        if k not in known:
            rep.warn(f"manifest has unrecognised key {k!r}")

    # ---- V3: referenced files ----
    for rel in [fw["rom"], man["briefing"]] + list(man.get("docs", [])):
        if not (pkg.dir / rel).exists():
            rep.err("V3", f"referenced file not found: {rel}")

    # ---- symbols and memory map ----
    sy = load_json(pkg, fw["symbols"], "V3", "symbols")
    mm = load_json(pkg, fw["memmap"], "V3", "memmap")
    if sy is None or mm is None:
        return rep
    try:
        pkg.symbols = {k: int(v, 16) for k, v in sy["symbols"].items()}
        pkg.fields = sy.get("fields", {})
        pkg.regions = [(int(r["lo"], 16), int(r["hi"], 16), r["name"])
                       for r in mm["regions"]]
    except (KeyError, ValueError, TypeError) as e:
        rep.err("V1", f"symbols/memmap malformed: {e}")
        return rep

    # ---- V10: purity ----
    has_checks = (pkg.dir / "checks").is_dir()
    declared = bool(man.get("impure"))
    if has_checks and not declared:
        rep.err("V10", "package has checks/ but does not declare \"impure\": true")
    if declared and not has_checks:
        rep.err("V10", "package declares \"impure\": true but has no checks/")
    if declared:
        rep.warn("package is IMPURE: it carries executable predicates and will "
                 "be refused by a daemon running in pure mode")

    # ---- setup ----
    if man.get("setup"):
        setup = load_json(pkg, man["setup"], "V3", "setup")
        if setup:
            for i, w in enumerate(setup.get("writes", [])):
                where = f"setup.writes[{i}]"
                widths = [k for k in ("u8", "u16", "u32", "hex") if k in w]
                if len(widths) != 1:
                    rep.err("V4", f"{where}: needs exactly one of u8/u16/u32/hex")
                addr = resolve(pkg, w.get("at", {}), where)
                if addr is not None:
                    n = {"u8": 1, "u16": 2, "u32": 4}.get(
                        widths[0] if widths else "u8", 1)
                    if widths and widths[0] == "hex":
                        n = len(str(w["hex"])) // 2
                    check_in_map(pkg, addr, n, where)
                if "note" not in w:
                    rep.warn(f"{where}: no 'note' — a bare offset with no "
                             f"explanation is unreadable six months on")

    # ---- objectives ----
    objs = load_json(pkg, man["objectives"], "V3", "objectives")
    if objs is None:
        return rep
    lst = objs.get("objectives")
    if not isinstance(lst, list) or not lst:
        rep.err("V1", "objectives file has no 'objectives' list")
        return rep
    pkg.objectives = lst

    seen = set()
    for o in lst:
        oid = o.get("id")
        if not oid:
            rep.err("V1", "objective without an 'id'")
            continue
        if oid in seen:
            rep.err("V8", f"duplicate objective id {oid!r}")
        seen.add(oid)
        for k in ("title", "brief", "success"):
            if k not in o:
                rep.err("V1", f"objective {oid!r} missing {k!r}")
        if "success" in o:
            check_predicate(pkg, o["success"], f"{oid}.success")
        if "fail" in o:
            check_predicate(pkg, o["fail"], f"{oid}.fail")
        for i, p in enumerate(o.get("partial", [])):
            if "when" not in p or "text" not in p:
                rep.err("V1", f"{oid}.partial[{i}]: needs 'when' and 'text'")
            else:
                check_predicate(pkg, p["when"], f"{oid}.partial[{i}].when")
        for i, h in enumerate(o.get("hints", [])):
            if not isinstance(h.get("after_frames"), int) or "text" not in h:
                rep.err("V1", f"{oid}.hints[{i}]: needs integer 'after_frames' "
                              f"and 'text'")
        if not o.get("hints"):
            rep.warn(f"objective {oid!r} has no hints")

    # ---- V7: dependency graph ----
    for o in lst:
        for dep in o.get("requires", []):
            if dep not in seen:
                rep.err("V7", f"objective {o['id']!r} requires unknown {dep!r}")
    graph = {o["id"]: [d for d in o.get("requires", []) if d in seen]
             for o in lst if o.get("id")}
    state = {}

    def cycle(n, stack):
        if state.get(n) == "done":
            return None
        if state.get(n) == "open":
            return stack[stack.index(n):] + [n]
        state[n] = "open"
        for d in graph.get(n, []):
            found = cycle(d, stack + [n])
            if found:
                return found
        state[n] = "done"
        return None

    for n in graph:
        c = cycle(n, [])
        if c:
            rep.err("V7", "dependency cycle: " + " -> ".join(c))
            break

    if strict and rep.warnings:
        rep.errors.extend(f"[strict] {w}" for w in rep.warnings)
    return rep


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("packages", nargs="+")
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    ap.add_argument("--quiet", action="store_true",
                    help="print only failures")
    a = ap.parse_args()

    bad = 0
    for p in a.packages:
        rep = validate(p, strict=a.strict)
        if rep.ok():
            if not a.quiet:
                print(f"PASS  {rep.name}")
                for w in rep.warnings:
                    print(f"      warn: {w}")
        else:
            bad += 1
            print(f"FAIL  {rep.name}")
            for e in rep.errors:
                print(f"      {e}")
            for w in rep.warnings:
                print(f"      warn: {w}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
