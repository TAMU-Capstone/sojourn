# Sojourn Platform Design

| | |
|---|---|
| **Document** | Platform Reference Architecture |
| **Project** | "Sojourn" Reverse Engineering Game Platform |
| **Version** | 1.0 |
| **Date** | September 3, 2026 |
| **Author** | Trevor Bakker |
| **Status** | **Advisory, not normative.** See §1. |

---

## 1. What This Document Is, and Is Not

Three documents are normative and you must conform to them:

- **Firmware Design Specification** — the probe, its memory map, its protocols.
- **Scenario Package Format** — what a scenario is, and the one daemon entry point conformance tests.
- **Introspection API** — how the daemon reads probe memory. Prescriptive down to the wire.

This document is different. It is **one known-good way to build the platform**, written because a schema and a conformance suite tell you what *must* be true without telling you where to start on a Monday morning. Nothing here is a requirement. If you have a better decomposition, take it — but be able to say what problem your version solves that this one does not, because every structure below exists to prevent a specific failure, and those failures are named.

The parts genuinely left to you: implementation language, web framework, storage engine, process model, module boundaries, the console's visual design, and how you test. The parts that are not yours to choose are in the three normative documents, and they are a small fraction of the system.

**Recommended language: Python 3.11+.** Not a requirement. The reasoning: the reference evaluator, validator and telemetry decoder are Python and are the executable definition of three interfaces; a Python daemon can read them as specification and, where sensible, share code. A team fluent in Go or TypeScript should use it and accept that they are reimplementing rather than reading.

---

## 2. System Context

```
   ┌──────────────┐   HTTP + WebSocket   ┌────────────────────────┐
   │   browser    │◄────────────────────►│                        │
   │   console    │                      │        daemon          │
   └──────────────┘                      │                        │
                                         │  ┌──────────────────┐  │
   ┌──────────────┐    reads at load     │  │ scenario loader  │  │
   │  scenario    │─────────────────────►│  │ evaluator        │  │
   │  packages    │                      │  │ session state    │  │
   │  (content)   │                      │  │ delay queue      │  │
   └──────────────┘                      │  │ command log      │  │
                                         │  └──────────────────┘  │
   ┌──────────────┐   append-only        │                        │
   │ mounted      │◄────────────────────►│                        │
   │ save volume  │                      └───────┬────────────┬───┘
   └──────────────┘                              │            │
                                    command chan │            │ introspection
                                    (UART/TCP)   │            │ (GDB RSP)
                                                 ▼            ▼
                                         ┌────────────────────────┐
                                         │   QEMU  ── the probe   │
                                         └────────────────────────┘
```

Four boundaries, and each is a place where a mistake is expensive:

| Boundary | Rule |
|---|---|
| Console ↔ daemon | The console renders and types. It holds no game rules — no objective evaluation, no budget arithmetic, no delay simulation. A player with dev-tools open must not be able to complete an objective. |
| Daemon ↔ packages | Read-only, at load. The daemon contains no scenario-specific constant (charter R11.3). If you find yourself writing `if scenario_id == ...`, the format is missing something — say so rather than special-casing. |
| Daemon ↔ probe | Two channels, never confused. See the Introspection API. |
| Daemon ↔ volume | All player state lives here (R14.1). Nothing survives in the container. |

---

## 3. Components

Ten of them. The dependency arrows all point downward; nothing below reaches up.

| # | Component | Owns | Must not |
|---|---|---|---|
| 1 | **Emulator supervisor** | Spawning QEMU, port allocation, liveness, restart-on-crash | Know anything about scenarios |
| 2 | **Command channel** | The UART socket, line framing, CRC suffixes, ACK/NAK correlation | Decide whether a command is *allowed* |
| 3 | **Introspection client** | GDB RSP, halt/read/resume, chunking, RLE | Ever write to the probe |
| 4 | **Telemetry decoder** | `TLM` line → frame dict, CRC check, event diffing | Know what an objective is |
| 5 | **Delay queue** | Holding uplinks for `uplink_delay_s`, frames for `downlink_delay_s` | Reorder anything |
| 6 | **Budget meter** | Counting charged commands per resource | Reject commands (that is policy, see §5) |
| 7 | **Command log** | Append-only JSONL, `seq`, `t_ms`, verbatim `raw` | Ever be rewritten |
| 8 | **Scenario loader** | Parsing, validating, symbol resolution, range collection | Evaluate anything |
| 9 | **Evaluator** | The predicate tree walk, latches, streaks | Talk to sockets |
| 10 | **Session** | Objective states, transitions, orchestration of the per-frame pass | Contain predicate logic |

Above these sit the **HTTP/WS API** and the **console**.

The two worth dwelling on:

**The evaluator is a pure function.** Give it a frame, an event list, a history, a memory-read callable, and a log; it returns booleans. It opens no sockets and reads no clock. This is what makes it unit-testable to R20.1's 70% line coverage without an emulator in the loop, and it is why the reference implementation can be an oracle at all.

**The session owns transitions, the evaluator owns truth.** Latching, `requires` gating and first-frame recording belong to the session. If latching leaks into predicate code you will not be able to test either half.

---

## 4. The Core Loop

The whole platform is one loop. Getting its order right is most of the correctness.

```
on each downlink frame arriving from the delay queue:

  1  decode the frame                            (telemetry decoder)
  2  if CRC bad -> record and skip; do not evaluate
  3  compute events against the previous frame   (telemetry decoder)
  4  drain the uplink delay queue: any command whose send time
     has arrived is written to the probe, charged, and appended
     to the command log                          (delay queue, budget, log)
  5  halt the guest                              (introspection)
  6  read every memory range this pass needs     (introspection)
  7  resume the guest                            (introspection)
  8  evaluate objectives in declaration order    (session + evaluator)
  9  push frame, events, objective deltas to the console  (WS)
 10  append this frame's state to history
```

Step 4 before 5–8 is deliberate: a command applied this tick must be visible to this tick's evaluation, or a player's final `POKE` appears to do nothing for one whole frame and they will re-send it. Steps 5–7 bracket 8 so every read in a pass sees one instant (Introspection API §5.4).

**Concurrency: don't.** Run this loop single-threaded, with one owner of the probe. Use async I/O for the sockets and the web server if you like, but let exactly one task drive the probe and mutate session state. Two writers to a probe is a class of bug you cannot reproduce, cannot log, and will spend three weeks on in week eleven.

---

## 5. Command Admission

When a player types a command, in order:

1. **Syntax** — non-empty, ≤ the probe's line limit. Reject locally.
2. **Checksum** — if `link.require_checksum`, verify or append. (Decide once whether the console or the daemon appends; document it. The reference evaluator appends in the daemon.)
3. **Budget** — if the resource is exhausted, refuse *at the daemon* with a clear message. A refused-for-budget command is **not** sent to the probe and **not** logged, because it never happened. This differs from a command the probe rejects, which is logged (format spec §8).
4. **Enqueue** with a send time of now + `uplink_delay_s`.
5. On send: write to the probe, charge the budget, append to the log with the probe's reply.

The distinction in 3 catches people out. *Budget* is the ground station declining to transmit. *NAK* is the spacecraft declining to comply. The first is not evidence of anything and costs nothing; the second is evidence, cost the player an uplink, and belongs in the record.

---

## 6. Replay Is the Save File

There is no snapshot. Restoring a session means replaying it (charter R15.1).

```
resume(session):
    boot a fresh probe from the package's ROM
    apply setup.json
    for each record in the command log, in seq order:
        wait until probe uptime >= record.t_ms
        write record.raw
    evaluating objectives at every frame boundary, exactly as in live play
```

This single mechanism gives you saves, command history, grading evidence, and portability across firmware upgrades. It costs you one hard constraint, which is worth stating plainly to whoever proposes the first shortcut:

> **Everything that determines an objective's state must be a pure function of (setup, command log, probe behavior).** No wall-clock time, no randomness, no ordering that depends on how fast the machine is.

The probe already holds up its end: sensor physics run off a fixed PRNG seed, the imaging easter egg rolls deterministically, and halting for introspection does not advance the guest clock. Your side of the bargain is that the daemon introduces nothing non-deterministic.

**The trap.** `t_ms` is *probe uptime when the command was applied*, not wall-clock and not when the player pressed Enter. Log wall-clock and replay reproduces a different session on a faster machine — and it will pass every test you write on your own laptop.

Design replay first, not last. A daemon that plays first and has replay bolted on in week 10 usually cannot be made deterministic without rewriting the loop.

---

## 7. State Ownership

One writer each. Where two components can write the same thing, decide now.

| State | Sole writer | Lives |
|---|---|---|
| Probe memory | The player, via `POKE` | The probe |
| Objective states | Session | Memory, derived; rebuilt by replay |
| Command log | Command channel, on send | Volume, append-only |
| Budget counters | Budget meter, on send | Derived from the log — do not persist separately |
| Profile | Profile store | Volume |
| Frame history | Session | Memory, bounded ring |

Budget being *derived* rather than stored matters: two sources of truth for a counter drift, and the log is the one that has to be right.

---

## 8. The Console

Diegetic — a mission-control console, not a quiz app. Panels:

| Panel | Content |
|---|---|
| **Downlink** | Raw `TLM` hex as it arrives, scrolling. Decoding it is the game — do not decode it here. |
| **Uplink** | Command line, history, and an in-flight indicator with a countdown for each command still crossing the gap. |
| **Mission status** | The objective list. See below. |
| **Event ticker** | ACK/NAK, reboots, mode changes. |
| **Budget** | Writes and reads remaining, as a resource, not a score. |
| **Link status** | The DSN complex and antenna in contact, signal activity, one-way delay. §8.2. |
| **Menu** | Start, abort, save, load, exit. §8.3. |

### 8.1 The objective panel

This is the contract the format's `objectives.json` exists to feed, and the part that most resembles a quest log.

```
MISSION STATUS — Bandwidth                        rev 3

  ✓  Diagnose the downlink                        complete   frame 5
  ✓  Attempt to redeploy the dish                 complete   frame 6
  ▸  Restore the radiation counter                active
       Get channel 0x04 back into the downlink and keep it there.
       The frame has room for exactly one science channel.

       ! The priority table has been modified but the radiation
         counter still is not surviving the squeeze. Check what you
         displaced: if you overwrote an entry rather than exchanging
         two, a channel has been lost from the table entirely.

       ? The table is a byte per channel, using the same channel IDs
         the downlink uses.                          [hint 2 of 3]

  ·  Keep the uplink budget                       locked
```

Rendering rules:

| Field | When shown |
|---|---|
| `title` | Always, for `active` and `complete`. For `locked`, show the title greyed or hide the objective entirely — pick one and be consistent. |
| `brief` | On transition to `active`. Never for `locked` — it leaks the next step. |
| `partial[].text` | While `active`, the first entry whose `when` holds this frame. Clears when none hold. Mark it visually as diagnosis, not instruction. |
| `hints[].text` | While `active` and incomplete, once the objective has been active for `after_frames` frames. Cumulative — revealing hint 2 does not hide hint 1. |
| `points`, `first_frame` | On completion. |

Two things the console must not do: re-order objectives (declaration order is authored), and show a `locked` objective's `brief` or `hints`.

**`hints` are console-only.** No evaluator reads them; the reference evaluator ignores them entirely. That means nothing has exercised the hint contract, so it is worth building this panel early and against the real packages.

### 8.2 The link panel

The panel modelled on NASA's DSN Now display. It is the piece that makes the delay felt rather than merely counted, so it is worth building properly.

```
  ┌────────────────────────────────────────────────────────────────────┐
  │ ▓▓ GOLDSTONE        DSS-25   34 m   X-band                         │
  │                                                                    │
  │      ╱▔▔╲        ╱▔▔╲        ╱▔▔╲        ╱▔▔╲        ╱▔▔╲          │
  │     ╱ 14 ╲      ╱ 23 ╲      ╱ 24 ╲      ╱▁25▁╲~~~~~ ╱ 26 ╲         │
  │                                          RECEIVING                 │
  │                                                                    │
  │  ONE-WAY  00:00:08     SPACECRAFT ANT  HGA      LINK  UP           │
  └────────────────────────────────────────────────────────────────────┘
```

**What drives it.** Everything on this panel is derived; none of it is decoration.

| Element | Source |
|---|---|
| Complex in contact | Probe uptime, unless the package pins one (R25.9) |
| Antenna carrying the link | The complex's dish list; aperture reflects the spacecraft antenna in use |
| Inbound animation | A downlink frame arriving |
| Outbound animation | An uplink in flight, for the duration of its delay |
| One-way delay | `link.downlink_delay_s` |
| Spacecraft antenna | The `COMMS` channel's antenna field, when the scenario decodes it |
| Link lost | No frame for more than two telemetry periods |

**Derive the complex from probe uptime, not the wall clock.** Earth turns, so each complex holds a deep-space target for roughly eight hours; rotating on that period gives a handover the player will actually notice across a long session. Using probe uptime rather than the host clock means a replayed session shows the same station sequence as the original, which is R25.9 and is the same determinism argument as everywhere else. The panel is display-only today, so a wall clock would not corrupt grading — but the moment someone adds pass windows that gate the uplink, it would, and by then the code is written.

**Do not fake activity.** A dish animating when nothing is being received teaches the player to ignore the panel. If the link is down, show it down.

**A note on scope.** Real station pass windows — the probe reachable only when a complex has it in view, uplinks queuing until the next pass — are a genuinely good mechanic and are **not in scope**. If they are added later they become objective-relevant, and the determinism rule above is what will make that possible without a rewrite.

### 8.3 Session lifecycle

```
   ┌──────┐  start ┌─────────┐  abort  ┌─────────┐
   │ idle │───────►│ running │────────►│ stopped │
   └──────┘        └─────────┘         └─────────┘
       ▲                │  save             │
       │                ▼                   │ resume
       │           (archive)                │
       └───────────── exit ◄────────────────┘
```

| Action | What it does | What it must not do |
|---|---|---|
| **Start** | Boot a probe from the package ROM, apply setup, begin the loop | Start a second probe. Starting while running requires confirmation and aborts the first (R26.2) |
| **Abort** | Kill the emulator, release ports, keep the log | Delete the log, or lose objective state — both are recovered by replay |
| **Save** | Write a portable archive: log, scenario id and revision, profile | Require stopping first, or snapshot emulator memory |
| **Load** | Restore by replay | Load an archive for a scenario that is not installed |
| **Exit** | Kill the emulator, flush the log, leave no orphan process | Leave a QEMU process holding a port — this is the one users will actually hit |

**Aborting is not a failure path, it is a normal one.** Players will start a scenario, realise they want to begin again, and expect that to be instant and clean. Make it a first-class action with a confirmation, not an error case.

**The orphaned emulator is the bug you will ship.** A probe launched as a child process and not reaped on exit holds its TCP ports, and the next start fails with an error that looks nothing like its cause. Make the supervisor own process lifetime from the beginning, kill on every exit path including exceptions, and verify with process inspection — which is why R26.6 is written to be checked that way.

### 8.4 API sketch

```
GET  /api/scenarios                 -> list from the content directory
POST /api/session                   {scenario_id, profile}  -> session id
GET  /api/session/{id}              -> full state, for reconnect
POST /api/session/{id}/uplink       {text} -> accepted | refused (+reason)
WS   /api/session/{id}/stream       -> events, below
```

WebSocket event types, one JSON object each: `frame` (raw hex + decoded), `event` (ticker line), `objective` (id, new state, partial text, hints unlocked), `budget`, `uplink_state` (queued / sent / replied).

Push deltas, not the whole world. A console that re-renders everything each frame will make the downlink panel unreadable.

---

## 9. Storage

```
/save/
  profile.json                    display name (R14.2), created on first run
  sessions/
    sojourn.comms.triage/
      log.jsonl                   the command log — the save file
      meta.json                   scenario revision, started_at, completion times (R16)
```

Keyed on scenario `id`. `meta.json` is a cache of things derivable from replay, kept so the scenario list can show progress without replaying everything at startup — but replay is authoritative, and if the two disagree the log wins.

R15.2 requires a volume written by version N to load in every later version. The mechanism that gives you this for free is that the log is append-only and its records carry only fields the format defines. Resist adding daemon-internal fields to log records.

---

## 10. Failure Modes

| Failure | Behavior |
|---|---|
| Probe crashes or exits | Restart from ROM, replay the log, tell the player. This is the same code path as resume — if it is not, one of them is untested. |
| Introspection connection lost | Abort the pass, leave states unchanged, attempt reconnect, tell the player grading is degraded. **Never** treat a failed read as false (Introspection API I15). |
| Frame fails CRC | Count it, show it in the ticker, skip evaluation for that frame. This is normal — it is a deep-space link. |
| Package fails validation | Refuse to list it, with the validator's message. Do not half-load. |
| `app_crc32` mismatch | Refuse to start, and say the package and firmware disagree. Do not let it fail later as a mysterious assertion. |
| Player bricks the probe | Nothing. The watchdog recovers it, the reboot counter increments, and the player sees it in telemetry. Do not intervene; this is a designed experience. |

---

## 11. Testing

R20.1 wants 70% line coverage on the evaluator and loader; R20.2 wants an end-to-end run in CI under ten minutes.

Four layers, fastest first:

1. **Evaluator unit tests** — no emulator. Feed synthetic frames and a fake memory callable. Every predicate op, every combinator, the temporal ones especially. This is where the coverage requirement is met, and it runs in a second.
2. **Loader/validator tests** — the nine seeded-defect packages in `conformance/defects/` are already written and each must be rejected by its specific rule.
3. **Replay determinism** — replay one log twice, assert identical objective states and identical `first_frame` values. Cheap, and it catches the entire class of §6 bugs.
4. **Conformance** — `conformance/run_conformance.py --daemon "<your command>"`. Fifteen checks. This is the acceptance gate; get it passing early and keep it passing, rather than aiming at it in week 12.

The `grader-hygiene` fixture deserves specific mention: it fails if you evaluate objectives over the player's command channel. If it fails on your first run, read the Introspection API before writing anything else.

---

## 12. Build Order

Mapped to the charter's milestones. The ordering exists to make the risky things fail early.

| Milestone | Build | Done when |
|---|---|---|
| **M1** wk 3 | Emulator supervisor; command channel; telemetry decoder; introspection client | You can boot a probe, type `PING`, see `ACK`, print decoded frames, and read `tlm_priority` over GDB — from a script, no UI |
| **M2** wk 6 | Delay queue; command log; evaluator; session; a minimal console | `first-contact` is playable end to end in a browser and its three objectives complete |
| **M3** wk 9 | Scenario loader + validator; persistence; replay; profiles | `comms-triage` loads from the content directory with no code change; restart mid-session restores state; `run_conformance.py` passes |
| **M4** wk 12 | Partial states, hints, budget panel, polish; `heater-runaway` added | A naive player completes `comms-triage` unaided; adding the third scenario touched no platform code (R11.2) |
| **M5** wk 14 | Container, network isolation, docs | One command from pull to playable in 120 s (R17.1) |

Two sequencing notes worth arguing about before you disagree:

**Build the introspection client in M1**, before you need it. It is eighty lines, it is fully specified, and discovering in week 8 that your evaluation reads corrupt the AUX channel means rewriting the loop.

**Build replay in M3, not M5.** Replay is not a feature, it is a property of the loop. Retrofitting it means finding every place you consulted a clock.

---

## 13. Risks

| Risk | Why it bites | What to do |
|---|---|---|
| Grading over the command channel | Plausible, simpler, and wrong in three ways that are all silent | Introspection API; the `grader-hygiene` fixture catches it |
| Non-deterministic replay | Passes on your laptop, fails on the grader's | `t_ms` is probe uptime; replay-twice test in CI from M3 |
| Game rules in the console | Convenient, then a player reads the JavaScript | All rules in the daemon; console renders |
| Scenario constants in platform code | Starts as one `if`, ends as R11.3 unverifiable | Loader is the only component that reads packages |
| Two writers to the probe | Unreproducible | One task owns the probe |
| Console built last | The hint and partial contracts have never been exercised by anything | Build the objective panel in M2, even ugly |
| Scope creep into firmware | The firmware is done and is not yours | If you need a firmware change, ask; there is usually a scenario-level answer |

---

## 14. Open to You

Deliberately unspecified, and we would like to see what you choose: the console's visual language; whether the daemon is one process or two; how you represent the predicate tree internally (interpreted each frame, or compiled once at load); whether the scenario list shows progress; how hints are paced; and whether a completed scenario can be replayed for a better budget score.

If any of those choices turn out to be constrained by something in the normative documents, that is a defect in those documents. Say so.

---

*Version 1.0 — advisory. The normative documents are the Firmware Design Specification, the Scenario Package Format, and the Introspection API.*
