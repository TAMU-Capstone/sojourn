# Writing a Sojourn Scenario

| | |
|---|---|
| **Document** | Scenario Author's Guide |
| **Project** | "Sojourn" Reverse Engineering Game Platform |
| **Version** | 1.0 |
| **Date** | September 3, 2026 |
| **Author** | Trevor Bakker |
| **Status** | Tutorial. The normative reference is the *Scenario Package Format*. Satisfies charter R12. |

---

## Before You Start

You need a built firmware tree and about an hour. Everything below is done with a text editor and two scripts; there is no authoring tool and you do not need one.

```
cd firmware
make            # builds, and writes build/symbols.json + build/memmap.json
make test       # 99 checks — confirm the probe is healthy before blaming a scenario
```

`build/symbols.json` is the file that makes authoring tractable. It maps every interesting name to an address, and it carries the **field offsets of the mission config block read out of the target's own debug information** — so you never compute an offset by hand.

This guide builds one complete scenario from nothing. It is a real scenario: it ships as `scenarios/heater-runaway/`, and every command shown here was run.

---

## The Scenario We Are Going to Write

**Cold Start.** The survival heater will not switch off. It draws 300 mW continuously, which pushes the bus over its power budget, so the autonomous power manager begins shedding instruments to compensate — and the player watches science channels vanish from the downlink for no commanded reason.

It is a good first scenario for three reasons. The cause and the symptom are two subsystems apart, so diagnosis is real work. The fix is two writes, so it is short. And there is an obvious wrong answer — restore the instrument without fixing the heater, and it gets shed again — which gives you something to write a diagnostic hint about.

---

## Step 1 — Copy a Skeleton (5 minutes)

```
cp -R scenarios/first-contact scenarios/heater-runaway
cd scenarios/heater-runaway
rm -f solution.txt solution.jsonl
```

You now have `manifest.json`, `briefing.md`, `objectives.json`, and a `firmware/` directory holding the probe image, `symbols.json` and `memmap.json`.

**Refresh the firmware binding** whenever you copy from an older package:

```
cp ../../firmware/build/{probe_rom.elf,symbols.json,memmap.json} firmware/
```

and take the CRC from the build output — `make` prints `crc32=0xf72478e0`. A package is bound to exactly one firmware build; the daemon refuses a mismatch up front rather than failing an assertion an hour into play.

---

## Step 2 — The Manifest (10 minutes)

```json
{
  "format": 1,
  "id": "sojourn.thermal.runaway",
  "title": "Cold Start",
  "revision": 1,
  "summary": "The survival heater will not switch off, and the power manager is shedding instruments to pay for it.",
  "difficulty": "tutorial",

  "firmware": {
    "rom": "firmware/probe_rom.elf",
    "symbols": "firmware/symbols.json",
    "memmap": "firmware/memmap.json",
    "app_crc32": "0xf72478e0"
  },

  "link": {
    "uplink_delay_s": 0,
    "downlink_delay_s": 0,
    "require_checksum": true,
    "budget": { "writes": 20, "reads": 400 }
  },

  "briefing": "briefing.md",
  "setup": "setup.json",
  "objectives": "objectives.json"
}
```

Three decisions here actually matter.

**`id`** is what save state is keyed on. Change it later and every player's progress on the old id is orphaned. Pick it once.

**Delay.** Zero for a tutorial. For anything that should feel like deep space, 8 seconds each way — long enough that a player stops typing speculatively and starts planning, short enough not to be tedious. `comms-triage` uses 8.

**Budget.** Writes are the scarce resource; reads should be generous, because you never want to punish looking. Twenty writes is tight for a two-write fix and leaves room to flail. Note that recovering a camera image costs 144 reads, so 400 is deliberately comfortable.

---

## Step 3 — Decide the Situation (15 minutes)

`setup.json` is what makes a scenario a scenario rather than a healthy probe. It runs before the player's first frame and is not charged or logged.

The firmware ships benign on purpose — every flight function's defaults keep the probe healthy — so a scenario is usually **two or three numbers moved**.

```json
{
  "format": 1,
  "writes": [
    {
      "at": { "sym": "g_config", "field": "heater_setpoint_dc" },
      "u16": 600,
      "note": "Thermostat setpoint raised to 60.0 C. The probe cruises near 27 C, so the heater can never reach setpoint and never switches off."
    },
    {
      "at": { "sym": "g_config", "field": "power_budget_mw" },
      "u16": 2050,
      "note": "Bus budget trimmed to 2050 mW. Nominal load is 1855; the stuck heater adds 300, so the power manager sheds the two lowest-priority loads."
    }
  ],
  "settle_frames": 2
}
```

Note `{"sym": "g_config", "field": "heater_setpoint_dc"}` — a name, not arithmetic. The config block mixes 8-, 16- and 32-bit members with compiler padding, and hand-counting through it is the single most common way to author a scenario that validates and then asserts against the wrong four bytes.

**Write the `note`.** It is ignored by everything. It is also the only thing that will explain this scenario to you in eighteen months.

**Do the arithmetic before you write the numbers.** The instrument draws are in `firmware/app/sensors.c`: MAG 180, IMU 90, THM 40, PWR 25, RAD 70, STR 310, CAM 60 — 775 mW, plus 1080 for the transmitter and dish steering, so 1855 nominal. The heater adds 300 → 2155. A budget of 2050 means the power manager sheds down its priority order (`shed_order` in `flight.c`: camera, radiation, star tracker, IMU, magnetometer) until it is under: camera (−60) → 2095, still over; radiation (−70) → 2025, under. Two sheds, and it stops.

That last part was chosen carefully. A budget of 2000 would also shed the **star tracker** — which is the high-gain antenna's attitude reference, so the dish would drift off boresight, the probe would fall back to the low-gain antenna, and the telemetry frame would start dropping channels for an entirely different reason. Correct behavior, and a completely confusing tutorial. **Check what your setup cascades into.**

`settle_frames: 2` lets the shedding happen before evaluation starts, so the player joins a situation already in progress.

---

## Step 4 — Write the Briefing (20 minutes)

`briefing.md` is shipped verbatim and is the only thing the player reads before starting. It is fiction, and it does real work: it tells them what is wrong without telling them where to look.

The one that ships opens:

> Sojourn is losing instruments, one at a time, and nobody commanded it to.
>
> The camera went first. Two frames later the radiation counter stopped
> reporting. Both are simply absent from the downlink now — not reading zero,
> absent — and the probe has raised no fault. Whatever is doing this believes
> it is behaving correctly.

Four things that make a briefing work:

**Lead with the observation, not the diagnosis.** "Instruments are disappearing" is what the ground sees. "The heater is stuck" is the answer.

**Name the symptom precisely.** *Absent, not zero* is a real distinction in this firmware and a player who misses it will chase the wrong thing. Teach it in prose once.

**Say what is not broken.** "It is not malfunctioning. It is doing exactly what it was told, in a situation nobody anticipated" — this is both true of the power manager and the most useful sentence in the briefing.

**Flag the ordering trap if there is one.** "Put them back in the wrong order and you will simply watch it be shed again." You are allowed to warn them; they still have to do it.

What not to do: no addresses, no register names, no offsets. Everything withheld is discoverable in the binary — that is the game.

---

## Step 5 — Find Your Addresses (10 minutes)

Open `firmware/symbols.json`. For anything in the config block, use `field`. For everything else:

```
python3 -c "import json; s=json.load(open('firmware/symbols.json'))['symbols']; print(s['tlm_priority'])"
```

Peripheral registers have no symbols — they are at fixed addresses by specification. The sensor block is eight 16-byte slots at `0x2001E000` in slot order (MAG, IMU, THM, PWR, RAD, STR, CAM, spare), so the radiation counter's control register is `0x2001E000 + 4*16 = 0x2001E040`. Camera registers start at `0x2001E100`, comms at `0x2001E200`; the firmware specification §4 has the map.

To see the probe's live state while you work, run the telemetry decoder against a bare probe:

```
cd firmware && python3 tools/tlm_decode.py --spawn
```

which prints decoded frames, housekeeping and link lines, and event notices as they happen. This is the fastest way to answer "what does this actually look like from the ground".

---

## Step 6 — Write the Objective (30 minutes)

```json
{
  "id": "stop-the-shedding",
  "title": "Stop the heater and recover the radiation counter",
  "brief": "Get the survival heater to switch off, and bring the radiation counter back into the downlink and keep it there.",
  "points": 30,
  "success": {
    "op": "sustained", "frames": 3,
    "of": { "op": "all", "of": [
      { "op": "tlm", "path": "channels.HK.heater_on", "cmp": "eq", "value": 0 },
      { "op": "channel_present", "id": "RAD" }
    ]}
  },
  "fail": { "op": "tlm", "path": "mode", "cmp": "eq", "value": "SAFE" }
}
```

**`sustained` rather than a bare condition** because the heater is hysteretic and the power manager acts once per cycle. A single frame where both happen to hold is not a fix. Three frames is.

### Assert the effect, not the method

The single most important habit. The success condition above says *the heater is off and the counter is reporting* — it does not say *the setpoint equals 100*. That matters because there is more than one honest fix: correct the setpoint, disable the thermostat, patch the comparison in `task_heater`, or raise the power budget so nothing is shed. Charter R9.2 asks for at least two distinct strategies per objective. Asserting on the effect gets that for free; asserting on a specific byte forbids every solution but yours.

Use `mem_*` predicates when the *state of memory is the goal* — a patched priority table, an injected routine in the code cave — not as a lazy proxy for behavior you could observe in telemetry.

### Predicate cookbook

| What you want to check | Use |
|---|---|
| A telemetry field has a value | `{"op":"tlm","path":"channels.HK.heater_on","cmp":"eq","value":0}` |
| A flag inside a status word | `{"op":"tlm_bits","path":"channels.COMMS.xstat","mask":4,"cmp":"eq","value":4}` |
| An instrument is reporting / has gone | `channel_present` / `channel_absent` — never "reads zero" |
| Something happened this frame | `{"op":"event","match":"ANTENNA HGA -> LGA"}` |
| A byte or word in memory | `mem_u8` / `mem_u16` / `mem_u32` |
| A bit in a control register | `{"op":"mem_bits","at":{...},"mask":8,"cmp":"eq","value":8}` |
| They patched *something* here | `{"op":"mem_changed","at":{...},"len":10}` |
| An exact byte pattern | `{"op":"mem","at":{...},"len":10,"cmp":"eq","value":"6160..."}` |
| They successfully ran a command | `{"op":"commanded","verb":"POKE","result":"ACK"}` |
| It stayed true | `{"op":"sustained","frames":3,"of":{...}}` |
| It was true at least once | `{"op":"ever","of":{...}}` |
| It happened recently | `{"op":"within","frames":20,"of":{...}}` |
| Within budget | `{"op":"budget","resource":"writes","cmp":"lte","value":40}` |

`all`, `any` and `not` compose any of these.

### Partial states are where the teaching happens

A `partial` entry fires while the objective is incomplete and shows the player *how* they are wrong. The first matching entry wins, so order them most-specific first.

```json
"partial": [
  { "when": { "op": "all", "of": [
      { "op": "tlm", "path": "channels.HK.heater_on", "cmp": "eq", "value": 0 },
      { "op": "channel_absent", "id": "RAD" } ]},
    "text": "The heater is off, so the load is back under budget and nothing more will be shed. But the radiation counter is still unpowered — the power manager switched it off and will not switch it back on. That is yours to undo." },

  { "when": { "op": "all", "of": [
      { "op": "channel_present", "id": "RAD" },
      { "op": "tlm", "path": "channels.HK.heater_on", "cmp": "eq", "value": 1 } ]},
    "text": "The counter is reporting again, but the heater is still drawing and the bus is still over budget. Expect the power manager to shed it a second time. Remove the cause before restoring the symptom." },

  { "when": { "op": "tlm", "path": "channels.HK.heater_on", "cmp": "eq", "value": 1 },
    "text": "The heater is still on. It compares a temperature against a setpoint; one of those two numbers is wrong, and it is not the temperature." }
]
```

Write one partial for each way you expect a competent person to be wrong. That is the whole design method: play it in your head, notice where you would go astray, and put a sentence there.

### Hints are a timed ladder

```json
"hints": [
  { "after_frames": 6,  "text": "Housekeeping channel 0x60 reports whether the heater is active and how many loads have been shed." },
  { "after_frames": 14, "text": "The thermostat is a task in the scheduler driven entirely by values in the configuration block." },
  { "after_frames": 24, "text": "A shed instrument is powered down at its control register, bit 0." }
]
```

Frames, not minutes — five seconds each, and it keeps hints deterministic under replay. Go from *where to look* to *what kind of thing it is* to *the mechanism*, and never to the address. Three is usually right.

---

## Step 7 — Validate (1 minute)

```
python3 firmware/tools/scenario_validate.py scenarios/heater-runaway
```

```
PASS  scenarios/heater-runaway
```

This catches unknown predicate ops, missing keys, symbols that do not exist, type mismatches, dependency cycles, and — the one that saves you an afternoon — any address that resolves outside the memory map. Run it on every save. Add `--strict` to make warnings fail.

---

## Step 8 — Solve It Yourself (20 minutes)

**Do not skip this.** A scenario nobody has solved end to end is not finished, and every mistake in this guide's "traps" section was found this way.

Write your move list as plain text, one uplink per line:

```
# restore the thermostat setpoint to 10.0 C (int16 little-endian, 0x0064)
POKE 0x2001913C 6400
# re-power the radiation counter the power manager shed
POKE 0x2001E040 01
```

Run it:

```
python3 firmware/tools/scenario_eval.py --scenario scenarios/heater-runaway \
    --script scenarios/heater-runaway/solution.txt \
    --record scenarios/heater-runaway/solution.jsonl --verbose
```

```
scenario sojourn.thermal.runaway rev 1
  frame   4  stop-the-shedding -> complete
```

A run takes about two minutes, because the probe emits one frame every five seconds and the evaluator waits for real frames.

**Then run the negative control.** Replace the move list with a single `PING` and confirm the objective *stays* `active`. An objective that completes when the player does nothing is the easiest mistake to make and the hardest to notice, because the happy path looks perfect.

```
  [{'id': 'stop-the-shedding', 'state': 'active', 'first_frame': None}]
```

---

## Step 9 — Keep the Fixture (5 minutes)

`--record` wrote `solution.jsonl`. Keep it with the package. It is instructor material, and it is also what stops this scenario from silently rotting: the conformance suite replays these logs, so if the firmware changes in a way that breaks a scenario, the suite fails instead of a student discovering it is unsolvable.

To add it to the suite, drop a `(package, fixture)` pair into `FIXTURES` in `conformance/run_conformance.py` and generate the expected state with `--out`.

---

## Traps

Every one of these was hit while writing the shipped packages.

**`commanded` without `result` matches a command the probe refused.** Rejected commands are logged on purpose — they cost budget and they are evidence. An objective meaning *they did this successfully* must say `"result": "ACK"`.

**An `event` predicate can match an event your own setup caused.** The first version of `comms-triage`'s redeploy objective completed off the antenna's *failure* event, before the player had done anything. If an objective is meant to record a player action, assert on the action — the command log, or a control-register bit — and use telemetry for the consequence.

**Hand-computed offsets.** Use `field`. Always.

**Asserting the method.** See Step 6. It forbids solutions you did not think of, and R9.2 explicitly wants those.

**Forgetting `sustained`.** Especially where a task acts once per cycle, or where you are distinguishing a routine that ran once from a hook that runs every cycle — which is the difference between the two hardest patch styles in the platform.

**Cascading setup.** Check what your initial conditions knock over two subsystems away. Read `flight.c` and `comms.c` before trimming a budget.

**Stale firmware binding.** If you rebuild the firmware, refresh `symbols.json`, `memmap.json`, `probe_rom.elf` and `app_crc32` together. Addresses move.

---

## Checklist

- [ ] `id` is final; `revision` bumped if the package has ever been played
- [ ] `firmware/` refreshed from the current build; `app_crc32` matches
- [ ] Every setup write has a `note` explaining why
- [ ] Setup cascades checked — nothing unintended is being shed, drifted or dropped
- [ ] Briefing names the symptom, withholds the answer, contains no addresses
- [ ] Success asserts effects, not a particular byte
- [ ] At least two honest solutions exist (R9.2) — write them down
- [ ] A partial state for each expected way to be wrong
- [ ] Hints go from where-to-look to mechanism, never to an address
- [ ] `scenario_validate.py` passes, `--strict` reviewed
- [ ] Solved end to end with `--script`, and the log recorded
- [ ] Negative control run: doing nothing leaves it incomplete
- [ ] `solution.txt` and `solution.jsonl` kept out of the player image (R19)

---

## Where to Look Next

Four patch styles the firmware supports, in difficulty order: change a value in the config block; change a threshold or enable that alters behavior; overwrite a branch in a function's entry pad or patch point; and inject a detour into the code cave that runs every cycle. A full reference scenario should exercise all four (R9.1). `firmware/README.md` documents the patching space, and firmware specification §6.5 explains the trampoline idiom.

Subsystems available and largely untouched by the shipped packages: the attitude control system and its propellant budget, the data recorder and its overflow, the imaging pipeline's transfer LUT and convolution kernel, the undocumented `AUTH`/`TRIM` verbs and the engineering key, and the two empty hook slots in the task table.

---

*Version 1.0 — every command in this guide was run against the reference build (`crc32 0xf72478e0`). The scenario it builds ships as `scenarios/heater-runaway/`.*
