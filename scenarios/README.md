# Reference Scenario Packages

Two worked packages, both **pure content** — no executable predicates, no
platform code. They are the material the *Scenario Package Format*
specification (`docs/SCENARIO_FORMAT.md`) describes, and the thing to copy
when authoring a third.

| Package | Objectives | What it exercises |
|---|---|---|
| `first-contact/` | 3 | Establishing the link, reading the downlink, powering down an instrument and proving from telemetry that its channel is *gone* rather than zero. Telemetry and command-log predicates. |
| `comms-triage/` | 4 | The Galileo bandwidth scenario. Diagnosis from the COMMS channel, the deliberate dead end of re-deploying a jammed dish, restoring the radiation counter by re-ranking the priority table, and doing it inside the uplink budget. Register, data and config patches; bit tests; `sustained`; budget accounting. |

## Running one

From the repository root:

```
python3 firmware/tools/scenario_validate.py scenarios/comms-triage
python3 firmware/tools/scenario_eval.py --scenario scenarios/comms-triage \
    --script scenarios/comms-triage/solution.txt --verbose
```

Each package carries a `solution.txt` — the intended move list, in plain text,
one uplink per line — and `solution.jsonl`, the command log that move list
produces. These are instructor material. They are also the fixtures the
conformance suite replays, which is what keeps them honest: if the firmware
changes in a way that breaks a scenario, `conformance/run_conformance.py`
fails rather than the scenario quietly becoming unsolvable.

A run takes about two minutes of wall clock, because the probe emits one
telemetry frame every five seconds and the evaluator waits for real frames
rather than fast-forwarding.

## Authoring a third

1. Copy `first-contact/` and change `manifest.json`'s `id` and `title`.
2. Refresh `firmware/` from a current build: `symbols.json`, `memmap.json` and
   `probe_rom.elf` from `firmware/build/`, and the `app_crc32` the build
   prints. A package is bound to one firmware build and the daemon refuses a
   mismatch rather than failing an assertion later.
3. Write `briefing.md` in fiction. It is shipped verbatim and it is the only
   thing the player reads before starting.
4. Write the objectives. Address memory as `{"sym": ..., "field": ...}`
   wherever a field name exists — the build reads config offsets out of the
   target's DWARF, so there is no reason to compute one by hand.
5. Validate, then solve it yourself with `--script`. A scenario nobody has
   solved end to end is not finished.

Two failure modes worth knowing about in advance, both found while writing
these two packages:

- **`commanded` without `"result": "ACK"` matches a rejected command.** The
  log records refusals deliberately (they cost budget and they are evidence),
  so an objective that means *they did this successfully* has to say so.
- **An `event` predicate can match an event the scenario itself caused.**
  The first version of `attempt-redeploy` completed off the antenna's *failure*
  event, before the player had done anything at all. If an objective is meant
  to record a player action, assert on the action — the command log, or a
  control-register bit — and use telemetry for the consequence.
