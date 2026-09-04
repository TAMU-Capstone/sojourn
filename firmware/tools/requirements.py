#!/usr/bin/env python3
"""requirements.py — build the requirements register from the charter.

The charter is the single register: every requirement has exactly one
identifier, defined there. The specifications explain and measure those
requirements but define no identifiers of their own. This tool exists to keep
that true.

It does three things:

  1. extracts every requirement from CHARTER.md into one sorted register
     (Markdown and CSV), so the whole set can be read in one place rather
     than hunted across eleven subsections;
  2. records which document carries the detailed treatment of each, by
     scanning the specifications for citations;
  3. CHECKS that no identifier is cited anywhere that the charter does not
     define, and that no requirement is defined twice.

    requirements.py --check              verify only; exit 1 on a problem
    requirements.py --write              regenerate docs/REQUIREMENTS.{md,csv}

Run --check in CI. A specification that invents its own numbering, or cites a
requirement that has been renumbered away, fails here rather than in a
student's understanding six weeks later.
"""
import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CHARTER = ROOT / "CHARTER.md"

# Specifications that carry detail for charter requirements. Order matters
# only for tidy output.
SPECS = [
    ("Firmware Design Specification", ROOT / "FIRMWARE_SPEC.md"),
    ("Scenario Package Format",       ROOT / "SCENARIO_FORMAT.md"),
    ("Introspection API",             ROOT / "INTROSPECTION_API.md"),
    ("Scenario Author's Guide",       ROOT / "SCENARIO_AUTHORING.md"),
    ("Platform Design (advisory)",    ROOT / "PLATFORM_DESIGN.md"),
]

PRI = {"T": "threshold", "O": "objective", "S": "stretch"}
VER = {"I": "inspection", "A": "analysis", "D": "demonstration", "T": "test"}

ROW = re.compile(r"^\|\s*(R\d+(?:\.\d+)?)\s*\|\s*([TOS])\s*\|\s*(.+?)\s*\|\s*([IADT])\s*\|\s*$")
SECTION = re.compile(r"^###\s+(6\.\d+)\s+(.*?)\s*$")
# Dotted identifiers are unambiguous citations. A bare "R7" is only treated as
# a citation when the charter actually defines it -- the firmware specification
# is full of ARM register names (r0, R1) that are not requirements.
CITE_DOTTED = re.compile(r"\bR\d+\.\d+\b")
CITE_BARE = re.compile(r"\bR\d+\b(?!\.\d)")


def parse_charter():
    """[(id, priority, text, verify, section number, section title)]"""
    reqs, sec_no, sec_title = [], "", ""
    for line in CHARTER.read_text().splitlines():
        m = SECTION.match(line)
        if m:
            sec_no, sec_title = m.group(1), m.group(2)
            continue
        m = ROW.match(line)
        if m:
            reqs.append((m.group(1), m.group(2), m.group(3), m.group(4), sec_no, sec_title))
    return reqs


def sec_key(item):
    """Numeric section ordering: 6.11 comes after 6.9, not after 6.1."""
    no = item[0][0]
    return tuple(int(x) for x in no.split("."))


def sort_key(rid):
    parts = rid[1:].split(".")
    return (int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)


def citations(defined):
    """requirement id -> [spec names citing it]"""
    out = {}
    for name, path in SPECS:
        if not path.exists():
            continue
        text = path.read_text()
        found = set(CITE_DOTTED.findall(text))
        found |= {r for r in CITE_BARE.findall(text) if r in defined}
        for rid in found:
            out.setdefault(rid, []).append(name)
    return out


def check(reqs, cites):
    problems = []
    defined = {r[0] for r in reqs}

    dupes = [k for k, v in Counter(r[0] for r in reqs).items() if v > 1]
    for d in sorted(dupes, key=sort_key):
        problems.append(f"{d} is defined more than once in the charter")

    for rid in sorted(set(cites) - defined, key=sort_key):
        where = ", ".join(cites[rid])
        problems.append(f"{rid} is cited by {where} but the charter does not define it")

    for rid, pri, text, ver, *_ in reqs:
        if "SHALL" not in text:
            problems.append(f"{rid} contains no SHALL")

    # a specification must not invent its own identifier scheme
    for name, path in SPECS:
        if not path.exists():
            continue
        stray = set(re.findall(r"\b([A-HJ-QSTUVWXYZ]\d+)\.\s", path.read_text()))
        if stray:
            problems.append(f"{name} defines its own identifiers: {sorted(stray)}")

    return problems


def write_register(reqs, cites):
    docs = ROOT / "REQUIREMENTS.md"
    rows = sorted(reqs, key=lambda r: sort_key(r[0]))
    by_sec = {}
    for r in rows:
        by_sec.setdefault((r[4], r[5]), []).append(r)

    n_t = sum(1 for r in rows if r[1] == "T")
    lines = [
        "# Sojourn Requirements Register",
        "",
        "| | |",
        "|---|---|",
        "| **Document** | Requirements Register — generated, do not edit |",
        "| **Project** | \"Sojourn\" Reverse Engineering Game Platform |",
        "| **Source** | `CHARTER.md` |",
        "| **Generated by** | `firmware/tools/requirements.py --write` |",
        "",
        "---",
        "",
        "## How to read this",
        "",
        "**The charter is the register.** Every requirement has exactly one identifier, "
        "defined in `CHARTER.md`. The specifications explain, measure and justify those "
        "requirements; none of them defines identifiers of its own. This file is generated "
        "from the charter so the two cannot drift, and `requirements.py --check` fails the "
        "build if a specification cites an identifier the charter does not define.",
        "",
        f"**{len(rows)} requirements**, of which {n_t} are threshold — the project fails "
        "acceptance without them.",
        "",
        "**Priority:** T threshold · O objective · S stretch. "
        "**Verify:** I inspection · A analysis · D demonstration · T test.",
        "",
        "## Index",
        "",
        "| Section | Requirements | Covers |",
        "|---|---|---|",
    ]
    for (no, title), rs in sorted(by_sec.items(), key=sec_key):
        ids = f"{rs[0][0]}–{rs[-1][0]}" if len(rs) > 1 else rs[0][0]
        lines.append(f"| §{no} | {ids} | {title} |")

    lines += ["", "---", "", "## Register", ""]
    for (no, title), rs in sorted(by_sec.items(), key=sec_key):
        lines += [f"### §{no} {title}", "",
                  "| ID | Pri | Requirement | Verify | Detail in |", "|---|---|---|---|---|"]
        for rid, pri, text, ver, *_ in rs:
            where = ", ".join(cites.get(rid, [])) or "—"
            lines.append(f"| **{rid}** | {pri} | {text} | {ver} | {where} |")
        lines.append("")

    docs.write_text("\n".join(lines) + "\n")

    csv_path = ROOT / "requirements.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "priority", "priority_name", "requirement",
                    "verify", "verify_name", "section", "section_title", "detail_in"])
        for rid, pri, text, ver, no, title in rows:
            w.writerow([rid, pri, PRI[pri], text, ver, VER[ver],
                        no, title, "; ".join(cites.get(rid, []))])
    return docs, csv_path, len(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    if not (a.check or a.write):
        a.check = a.write = True

    reqs = parse_charter()
    cites = citations({r[0] for r in reqs})

    if a.check:
        problems = check(reqs, cites)
        if problems:
            print(f"FAIL  {len(problems)} problem(s):")
            for p in problems:
                print("      " + p)
            return 1
        print(f"PASS  {len(reqs)} requirements, one identifier each, "
              f"every citation resolves")

    if a.write:
        md, csvp, n = write_register(reqs, cites)
        print(f"wrote {md.name} and {csvp.name} ({n} requirements)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
