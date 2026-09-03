#!/usr/bin/env python3
"""run_conformance.py — the acceptance gate for a Sojourn game daemon.

Two suites:

  VALIDATION   Every package in conformance/defects/ must be rejected by the
               team's validator, each by the rule it was seeded for, and the
               two reference packages must pass. This is charter R13.

  REPLAY       For each fixture, invoke the daemon's conformance entry point

                   <daemon> conform --scenario DIR --replay LOG --out FILE

               and compare the objective states it reports against expected
               output generated from real firmware runs. This is the whole
               acceptance gate for the scenario format: nothing else about
               the daemon is dictated.

Usage:
    run_conformance.py --daemon "python3 ../mydaemon/main.py"
    run_conformance.py --daemon ./sojournd --validator ./myvalidate
    run_conformance.py --reference          # check the fixtures against the
                                            # reference evaluator instead

Exit status 0 if every case passes.
"""
import argparse
import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIOS = HERE.parent / "scenarios"
REF_EVAL = HERE.parent / "firmware" / "tools" / "scenario_eval.py"
REF_VALIDATE = HERE.parent / "firmware" / "tools" / "scenario_validate.py"

# (package directory, fixture stem). Packages live under scenarios/ unless
# the directory exists here, which is how the conformance-only fixtures stay
# out of player-facing content.
FIXTURES = [
    ("first-contact",  "first-contact-solution"),
    ("comms-triage",   "comms-triage-solution"),
    ("comms-triage",   "comms-triage-passive"),
    ("heater-runaway", "heater-runaway-solution"),
    ("grader-hygiene", "grader-hygiene"),
]


def compare(expected, got):
    """Objective states and their order are what conformance checks.

    Frame numbers are NOT compared: a daemon that schedules commands against
    transmission delay will legitimately reach the same verdicts on different
    frames than the reference evaluator, which applies one move per frame.
    """
    problems = []
    if got.get("scenario") != expected["scenario"]:
        problems.append(f"scenario id: expected {expected['scenario']!r}, "
                        f"got {got.get('scenario')!r}")
    exp = {o["id"]: o["state"] for o in expected["objectives"]}
    gt = {o["id"]: o["state"] for o in got.get("objectives", [])}
    for oid, state in exp.items():
        if oid not in gt:
            problems.append(f"objective {oid!r} missing from output")
        elif gt[oid] != state:
            problems.append(f"objective {oid!r}: expected {state}, got {gt[oid]}")
    for oid in gt:
        if oid not in exp:
            problems.append(f"unexpected objective {oid!r} in output")
    eb, gb = expected.get("budget", {}), got.get("budget", {})
    for res in ("writes", "reads"):
        if res in eb and eb[res] != gb.get(res):
            problems.append(f"budget {res}: expected {eb[res]}, got {gb.get(res)}")
    return problems


def run_validation(validator, quiet):
    print("== validation suite (charter R13) ==")
    passed = failed = 0

    for pkg in sorted(SCENARIOS.iterdir()):
        if not (pkg / "manifest.json").exists():
            continue
        r = subprocess.run(validator + [str(pkg)], capture_output=True, text=True)
        ok = r.returncode == 0
        print(f"  [{'PASS' if ok else 'FAIL'}] reference package accepted: {pkg.name}")
        if not ok:
            print("        " + r.stdout.strip().replace("\n", "\n        "))
        passed, failed = passed + ok, failed + (not ok)

    cases = json.load(open(HERE / "defects.json"))["cases"]
    for c in cases:
        d = HERE / c["dir"]
        r = subprocess.run(validator + [str(d)], capture_output=True, text=True)
        rejected = r.returncode != 0
        right_rule = f"[{c['expect_rule']}]" in r.stdout
        ok = rejected and right_rule
        name = Path(c["dir"]).name
        print(f"  [{'PASS' if ok else 'FAIL'}] seeded defect rejected "
              f"({c['expect_rule']}): {name}")
        if not ok:
            reason = ("accepted the package" if not rejected
                      else f"rejected, but not by {c['expect_rule']}")
            print(f"        {reason} — {c['why']}")
        passed, failed = passed + ok, failed + (not ok)

    return passed, failed


def run_replay(daemon, quiet):
    print("== replay suite ==")
    passed = failed = 0
    for scen, fixture in FIXTURES:
        pkg = HERE / scen if (HERE / scen / "manifest.json").exists() else SCENARIOS / scen
        log = HERE / f"{fixture}.jsonl"
        expected = json.load(open(HERE / f"{fixture}.expected.json"))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "state.json"
            cmd = daemon + ["conform", "--scenario", str(pkg),
                            "--replay", str(log), "--out", str(out)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
            if r.returncode != 0 or not out.exists():
                print(f"  [FAIL] {fixture}: daemon exited {r.returncode}")
                if r.stderr.strip():
                    print("        " + r.stderr.strip()[:400].replace("\n", "\n        "))
                failed += 1
                continue
            got = json.load(open(out))
        problems = compare(expected, got)
        if problems:
            print(f"  [FAIL] {fixture}")
            for p in problems:
                print(f"        {p}")
            failed += 1
        else:
            n = len(expected["objectives"])
            print(f"  [PASS] {fixture} ({n} objectives agree)")
            passed += 1
    return passed, failed


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--daemon", help="command that implements 'conform' (§10)")
    ap.add_argument("--validator", help="command that validates a package")
    ap.add_argument("--reference", action="store_true",
                    help="run against the reference evaluator and validator")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    if a.reference:
        daemon = [sys.executable, str(REF_EVAL)]
        validator = [sys.executable, str(REF_VALIDATE), "--quiet"]
    else:
        if not a.daemon:
            ap.error("give --daemon, or --reference to check the fixtures")
        daemon = shlex.split(a.daemon)
        validator = (shlex.split(a.validator) if a.validator
                     else [sys.executable, str(REF_VALIDATE), "--quiet"])

    p1, f1 = run_validation(validator, a.quiet)
    p2, f2 = run_replay(daemon, a.quiet)

    total_p, total_f = p1 + p2, f1 + f2
    print()
    print(f"{total_p} passed, {total_f} failed")
    return 1 if total_f else 0


if __name__ == "__main__":
    sys.exit(main())
