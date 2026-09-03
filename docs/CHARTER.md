# Project Charter & Requirements — "Sojourn"
## A Reverse Engineering Game Platform (Software & Cybersecurity Capstone)

| | |
|---|---|
| **Document** | Project Charter and Requirements Specification |
| **Version** | 0.3 (Draft — uplink budget meters writes only; new R4.3 read allowance) |
| **Date** | August 26, 2026 |
| **Sponsor** | Trevor Bakker (Instructor) |
| **Team** | 5–6 Computer Science students, one semester |
| **Status** | Draft for team review |

---

## 1. Project Summary

The team will build a **reverse engineering game platform** in which a player takes the role of a mission operations engineer for an aging deep-space probe. The probe's source code has been lost; only the flight binary, a memory map, and partial "recovered" documentation survive. To keep the mission alive, the player must reverse engineer the ARM firmware and uplink commands that read and overwrite portions of probe memory — disabling failing subsystems, altering mission parameters, and eventually injecting new functionality — exactly as NASA has done for the Voyager probes.

The player experience is a tight feedback loop: analyze the binary offline in a disassembler, compose an uplink through a ground-station console, wait out a simulated transmission delay, and read the resulting downlink telemetry to learn whether the change took effect.

The capstone team does **not** primarily build a game level — it builds the **platform**: an emulated probe, a command uplink/downlink protocol, a ground-station console, a scenario engine with live objective checking, and exactly **one polished reference scenario** proving the platform works. The platform will later serve as courseware for a reverse engineering course, so **extensibility is a first-class requirement**: adding a future mission must require authoring content, not modifying code.

## 2. Objectives & Success Criteria

The project succeeds if, at the end of the semester:

1. A student can be handed a container image, run it locally with one command, open the ground-station console in a browser, and play the reference scenario end to end with no instructor assistance.
2. The player receives **immediate, layered feedback** for every uplink: protocol ACK/NAK, observable telemetry changes, and objective status transitions — including partial-progress feedback.
3. The probe can be **bricked and recovered**: a destructive patch causes a watchdog reset to a protected golden image, observable in telemetry, without losing the player's saved progress.
4. A **new scenario can be authored without touching platform code**: the instructor demonstrates this by dropping a second scenario package (however small) into the content directory and playing it.
5. Player progress (completed objectives, command history) survives container restarts and image upgrades via a mounted volume.
6. All five components (firmware, emulation harness, game daemon, console, scenario format) are documented well enough that a future course team can maintain them.

**Explicit non-goals (out of scope for the semester):** multi-tenant hosting, accounts/authentication beyond a local player profile, anti-cheat or tamper-proofing of the container, real-time multiplayer, more than one full-length scenario, mobile clients, and instructor-side grading infrastructure (the design must not preclude it later — see §6.7 — but none is built this semester).

**Threat model, stated plainly:** the player owns the container and can inspect everything in it, including the objective checker. This is accepted. A student who cheats by reverse engineering the grader has, in a meaningful sense, completed the exercise. No secrets required for grading may therefore ever ship in the image.

## 3. Background & Motivating Example

In 2023–2024, NASA JPL revived Voyager 1 — 15 billion km away, 22-hour one-way light time — by diagnosing a failed memory chip in the Flight Data Subsystem from garbled telemetry alone, then relocating and patching the affected code by poking new bytes into memory, section by section, with no ability to test on the real hardware first. Sensor shutdowns to conserve Voyager 2's power budget follow the same pattern: small, surgical, irreversible-feeling memory writes, verified only through downlink telemetry.

This project compresses that experience into a game: the same constraints (opaque binary, narrow uplink, telemetry-only feedback, real consequences for mistakes) at a scale a student can master in weeks rather than a career.

## 4. Player Experience (Definitive Description)

The following narrative is normative — the platform must support every beat of it.

> The player unpacks the mission archive: a container image, `probe.bin` (the flight firmware), a memory map, and the *Recovered Mission Operations Manual* — authentic-looking but incomplete documentation of the probe's subsystems, telemetry format, and command protocol. They start the container and open the ground-station console in a browser: a terminal-style interface showing a live downlink telemetry feed and an uplink command line.
>
> Mission control (the scenario's briefing) reports that the probe's magnetometer is failing, flooding the downlink and draining the power budget. The player's first objective: power it down. They load `probe.bin` into Ghidra alongside the memory map, find the sensor polling table, and identify the byte that enables the magnetometer channel.
>
> They compose an uplink: `POKE 0x20001A44 00`, with the required checksum. The console shows the frame leaving, then a transmission-delay countdown. The probe ACKs: command received, address writable, byte written. One telemetry cycle later, the MAG field vanishes from the downlink frames and the power-draw value drops. The mission status panel flips: **OBJECTIVE 1 COMPLETE — persisted to the save file.**
>
> Later objectives escalate: change a comms parameter (patch a config value), disable a subsystem outright (patch code, not just data), and finally install new behavior (assemble a small routine, poke it into free RAM, and hook it into the main loop). At some point the player fat-fingers an address, corrupts the scheduler, and the probe goes silent — then telemetry returns with the reboot counter incremented and uptime at zero: the watchdog restored the golden image. Their completed objectives are intact; their in-RAM patches are gone; they re-send them from command history and continue.

## 5. System Architecture

Five components, one container, one clean seam between **platform** and **content**.

```
Ground-Station Console  (browser · xterm.js · telemetry feed · uplink line · status panel)
        ▲ │   WebSocket / HTTP
        │ ▼
Game Daemon  (scenario engine · objective evaluator · uplink/downlink relay ·
              delay & bandwidth sim · command log & saves)
        ▲ │   virtual UART (command protocol)  +  introspection (GDB stub / monitor API)
        │ ▼
Emulated Probe  (ARM Cortex-M firmware on Renode/QEMU · watchdog & golden image)

— all inside one container —
content: /scenarios/*  (drop-in packages)      mounted volume: /savedata  (saves, command log)
```

### 5.1 Probe Firmware (content + one reference implementation)

Bare-metal C for **ARM Cortex-M (Thumb-2)**. Chosen deliberately: it is what Ghidra handles cleanly, it is simple to emulate, and it is authentic to real spacecraft-class embedded software. The reference firmware implements: a cooperative main loop, a sensor subsystem table (the primary patch target), a telemetry encoder emitting periodic downlink frames, a command interpreter (PEEK/POKE/CALL/status), a watchdog, and a protected golden-image recovery path. Firmware source is a *platform deliverable* (for future scenario authors) but is **never shipped to players** — players get only the built binary, memory map, and manual.

### 5.2 Emulation Harness (platform)

Runs the firmware under **Renode (preferred) or QEMU** with: a virtual UART carrying the command protocol, a machine-readable introspection interface (memory reads, register state, execution state) consumed by the game daemon, and watchdog/reset modeling. One probe instance per container — solo play is the design point. **This is the highest-risk component: a "hello probe" (firmware answering a ping over emulated UART, memory readable via introspection) is due by Week 3 (M1).**

### 5.3 Game Daemon (platform)

A local service that owns everything between the emulator and the browser: loads scenario packages; relays uplink frames to the probe (enforcing the scenario's transmission delay, bandwidth budget, and checksum rules); decodes nothing about the firmware itself — all firmware-specific knowledge lives in the scenario package; continuously evaluates objective assertions against emulator state and telemetry after each downlink cycle; appends every uplink to a persistent, timestamped **command log**; and writes save state. **Progress persistence is by command-log replay:** on restart, the daemon replays the logged uplinks against a fresh probe instance rather than snapshotting emulator memory. This makes saves trivially portable across image upgrades and gives command history, save/restore, and (future) grading evidence from a single mechanism.

### 5.4 Ground-Station Console (platform)

Browser-based (xterm.js or equivalent), served by the daemon. Panels: live downlink telemetry feed (raw frames — decoding them is part of the game); uplink command line with history; transmission-delay countdown for in-flight commands; mission status panel (objectives with pending / partial / complete states and unlock-on-completion briefing text); and an event ticker (ACK/NAK, watchdog resets). Presentation should be diegetic — a mission-control console, not a quiz app.

### 5.5 Scenario Package Format (platform's most important deliverable)

A scenario is **pure content**: a directory (or archive) containing

- `manifest` — metadata, ordering/dependencies of objectives, delay/bandwidth parameters;
- `firmware.bin` + memory map — the probe image and its layout;
- `docs/` — the player-facing recovered manual (shipped verbatim);
- `objectives/` — one declarative entry per objective: briefing text, and **win conditions as machine-checkable assertions** over (a) memory state read via introspection and (b) telemetry field predicates, with optional **partial-progress states** carrying diagnostic hint text (e.g., "sensor silenced but power draw unchanged — did you stub the readout instead of cutting power?").

The assertion language is the platform's core abstraction. It must be expressive enough for the reference scenario's hardest objective (code injection) and simple enough that an instructor can author it from documentation alone. The acceptance test is objective #4 in §2: **a new scenario is added with zero platform-code changes.**

## 6. Requirements

**Convention.** **SHALL** denotes a binding, individually verifiable requirement. **WILL** denotes a statement of fact or sponsor intent requiring no verification. SHOULD/MAY do not appear in requirement statements; negotiability is captured in the Priority column. **Priority:** **T** = threshold (the project fails acceptance without it), **O** = objective (expected; negotiable under §9 schedule pressure), **S** = stretch. **Verify:** **I** = inspection, **A** = analysis, **D** = demonstration, **T** = test (automated).

**Sponsor-furnished items.** The sponsor WILL supply the reference flight firmware (golden image, memory map, instructor-side symbol map) before the semester begins, and WILL co-author the recovered manual and all scenario fiction. The platform WILL be evaluated against these requirements at the acceptance demonstration (§10).

### 6.1 Gameplay & Feedback

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R1.1 | T | The probe SHALL reply to every uplink frame delivered to its UART with `ACK` or `NAK <code>` within 2 s of delivery (simulated transmission delay excluded). | T |
| R1.2 | T | ACK/NAK replies SHALL encode command receipt and execution status only; no probe reply SHALL encode objective state. | I |
| R2.1 | T | The daemon SHALL re-evaluate every active objective assertion within one telemetry period of receiving each downlink frame. | T |
| R2.2 | T | Objective state SHALL be derived solely from introspected probe memory and decoded telemetry; the platform SHALL expose no player-accessible input that sets objective state directly. | I |
| R3.1 | T | Every objective SHALL be in exactly one of three states at all times: pending, partial, or complete. | T |
| R3.2 | T | Within 2 s of an objective entering a partial state, the console SHALL display that state's scenario-authored hint text. | D |
| R3.3 | T | An objective that reaches complete SHALL remain complete for the rest of the scenario run, and the completion SHALL be persisted to the save volume within 5 s. | T |
| R4.1 | T | The daemon SHALL delay each uplink by the scenario-configured one-way transmission delay, configurable from 0 to 3600 s in 1 s increments. | T |
| R4.2 | T | The daemon SHALL meter **only state-changing uplinks** (`POKE`, `CALL`, `TRIM`, `SAFE`) against the scenario-configured command budget (1–1000 commands per window; window length 10–86 400 s), and SHALL reject each over-budget command with a distinct console error without forwarding it to the probe. | T |
| R4.3 | T | Read-only uplinks (`PING`, `STAT`, `PEEK`, `DUMP`, `AUTH`) SHALL NOT consume the command budget. Where a scenario limits observation it SHALL do so through a separate read allowance, configurable 1–10 000 commands per window. | T |
| R5.1 | T | If the application fails to reload the watchdog for 3 s (±1 tick at 100 Hz), the firmware SHALL reset and restore the golden image. | T |
| R5.2 | T | Within 10 s of a watchdog reset, downlink telemetry SHALL resume with the reboot counter incremented by exactly 1 and reported uptime under 10 s. | T |
| R5.3 | T | A POKE addressed to any protected region SHALL return `NAK E04` and SHALL leave all probe memory unmodified. | T |
| R6.1 | O | The console SHALL retain and recall at least the most recent 500 uplink commands per player across sessions. | D |
| R6.2 | O | The console SHALL transmit a player-supplied batch file of up to 100 commands in file order, subject to the same delay and budget enforcement as typed commands. | D |
| R7 | S | A player-triggered scenario reset, if provided, SHALL preserve the command log and no other player state. | D |

> **Why reads and writes are metered separately.** A budget tight enough to make each patch feel consequential (tens of commands) cannot also accommodate recovering an image, which costs 144 `PEEK`s at 96×96 — or 18 with bulk downlink enabled. The budget exists to make *decisions* costly, not to punish observation, and real missions meter command uplink and downlink bandwidth as different resources. Metering only writes lets a scenario run a genuinely tight patch budget and a full image downlink at the same time without either distorting the other.

### 6.2 Reverse Engineering Surface

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R8.1 | T | The player-facing firmware SHALL be bare-metal ARM Thumb-2 targeting Cortex-M4, with no OS or runtime beyond the shipped image. | I |
| R8.2 | T | `probe.bin` plus the published memory map SHALL load into stock Ghidra (v11.0 or later) such that auto-analysis completes with no manual processor configuration and identifies ≥ 90 % of application functions, measured against the instructor-side symbol map. | D |
| R9.1 | T | The reference scenario SHALL contain at least 4 graded objectives, including at least one each of: data patch, configuration patch, code patch, and code injection. | D |
| R9.2 | O | Each graded objective SHALL be solvable by at least 2 distinct patch strategies, both documented instructor-side. | A |
| R10.1 | T | Every telemetry field documented in the recovered manual SHALL be decodable by a tester using only the manual and captured downlink frames. | D |
| R10.2 | T | At least 1 telemetry channel SHALL be present in downlink frames and absent from the recovered manual. | I |

### 6.3 Extensibility

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R11.1 | T | The daemon SHALL discover and load every conforming scenario package present under the content directory at startup, with no platform code change, rebuild, or configuration edit. | T |
| R11.2 | T | Installing a second scenario SHALL require only copying one directory into the content directory, verified by an empty diff across all platform repositories. | D |
| R11.3 | T | All firmware-specific knowledge (addresses, telemetry formats, objective assertions) SHALL reside in scenario packages; platform source SHALL contain no scenario-specific constants. | I |
| R12 | T | The scenario-author's guide SHALL enable the sponsor, working unaided, to author and successfully run a new one-objective scenario in at most 4 hours. | D |
| R13 | O | The scenario validation tool SHALL flag 100 % of seeded defects in a test corpus containing at least 3 cases each of: malformed manifest, unparsable assertion, and assertion address outside the memory map. | T |

### 6.4 Persistence & Identity

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R14.1 | T | 100 % of player state (profile, per-scenario objective states, command log) SHALL reside on the mounted volume; no player state SHALL be written to the container filesystem. | T |
| R14.2 | T | The player profile SHALL consist of a locally chosen display name of 1–32 characters; the platform SHALL require no authentication. | I |
| R15.1 | T | After a container restart, command-log replay SHALL restore all objective states to their pre-restart values within 60 s for logs of up to 500 commands. | T |
| R15.2 | T | A save volume written by platform version N SHALL load without loss in every later version released during the semester. | T |
| R16 | O | For each completed objective, the platform SHALL record the completion timestamp and the cumulative uplink count at completion, and SHALL display both on a profile screen. | D |

### 6.5 Deployment

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R17.1 | T | One documented command SHALL take a reference machine (4 CPU cores, 8 GB RAM, Docker Engine ≥ 24; Linux, macOS, or Windows with WSL2) from pulled image to a playable console in at most 120 s. | D |
| R17.2 | O | The container image SHALL be at most 4 GB. | I |
| R18 | T | During play, the container SHALL initiate zero outbound network connections, verified by packet capture over one complete scenario run. | T |
| R19 | T | The container image SHALL contain no instructor-only data (solution states, grading keys, symbol maps), verified by review of the image manifest and layers. | I |

### 6.6 Quality & Documentation

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R20.1 | T | The assertion evaluator and scenario loader SHALL each have automated tests achieving at least 70 % line coverage. | T |
| R20.2 | T | An automated end-to-end test SHALL play the reference scenario to completion through the daemon API in at most 10 minutes, and SHALL run in CI on every merge to the default branch. | T |
| R21 | T | Delivery SHALL include exactly these documents: player quickstart, scenario-author's guide, platform architecture & maintenance guide, and the reference scenario's recovered manual. | I |

### 6.7 Future-Proofing

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R22.1 | T | Each command-log entry SHALL contain: a monotonically increasing sequence number, a UTC timestamp, the raw uplink text, the probe's reply, and the delivery status. | T |
| R22.2 | O | The command-log format SHALL be versioned and documented such that an instructor-side replay verifier can be built with no platform changes, confirmed by analysis at the design review. | A |

## 7. Team Organization

Roles for 5–6 students; each owns a component and its documentation and tests. Integration is everyone's job, but the Protocol & Integration owner is accountable for it.

| Role | Owns | Key deliverables |
|---|---|---|
| **Firmware / Scenario Engineer** | §5.1 | Reference firmware, memory map, golden image, difficulty-ramp objectives, recovered manual (with instructor) |
| **Emulation Engineer** | §5.2 | Renode/QEMU harness, introspection API, watchdog/reset modeling, M1 "hello probe" |
| **Platform Engineer(s)** (1–2) | §5.3, §5.5 | Game daemon, scenario loader, assertion evaluator, delay/budget enforcement, persistence & replay |
| **Frontend Engineer** | §5.4 | Ground-station console, telemetry feed, mission status panel, diegetic presentation |
| **Protocol & Integration Engineer** | seams | Uplink/downlink protocol spec, scenario package schema + validation tool (R13), CI, end-to-end test (R20), release engineering |

With five students, the Protocol & Integration role merges into the Platform role. The instructor acts as product owner and co-authors all player-facing fiction and documentation.

## 8. Milestones (15-week semester)

| Milestone | Week | Exit criteria |
|---|---|---|
| **M0 — Design freeze** | 2 | Protocol spec, scenario package schema, and introspection API drafted and reviewed; repos and CI up |
| **M1 — Hello probe** | 3 | Firmware answers ping over emulated UART; daemon reads probe memory via introspection. *Schedule-risk gate: if M1 slips past week 4, cut scope (see §9) rather than compress later milestones* |
| **M2 — Vertical slice** | 6 | One hard-coded objective playable end to end in the browser: uplink → delay → ACK → telemetry change → objective completes |
| **M3 — Platform feature-complete** | 9 | Scenario packages load from content dir; assertions drive objectives incl. partial states; persistence/replay works; watchdog/golden image works |
| **M4 — Reference scenario complete** | 12 | Full difficulty ramp playable; recovered manual written; end-to-end test passes; second mini-scenario added with zero code changes (proves R11) |
| **M5 — Release** | 14–15 | Playtested with naive users; docs complete; container published; final presentation |

## 9. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Emulation harness harder than expected | Med | High | M1 gate at week 3; fallback from Renode to plain QEMU + GDB stub; last-resort fallback to an instrumented interpreter for a subset of the firmware |
| Assertion language over-engineered | Med | Med | Design it from the reference scenario's real objectives, not speculatively; R12's worked example is the scope fence |
| Reference scenario content squeezed by platform work | High | Med | Instructor co-authors fiction/docs in parallel from week 1; objectives 1–2 authored against the M2 vertical slice |
| Team integration late-semester crunch | Med | High | Vertical slice at M2 forces early integration; end-to-end test in CI from M3 |
| Scope creep (multiplayer, accounts, anti-cheat) | Med | Med | Non-goals in §2 are contractual; changes require sponsor sign-off |

**Pre-agreed scope cuts, in order:** (1) drop R13 validation tool, (2) drop scoring beyond completion tracking (R16), (3) reduce ramp to three objectives (defer code injection to a documented stretch scenario), (4) simplify console to a single-pane terminal. The scenario-package seam (R11) and the feedback loop (R1–R5) are never cut — they are the project.

## 10. Acceptance & Handoff

Final acceptance is a live demonstration by the instructor, unassisted, of: pulling the image, playing the reference scenario's first two objectives, deliberately bricking the probe and recovering, restarting the container and confirming restored progress, and installing the second mini-scenario by copying a directory. Handoff includes all repositories, the container build pipeline, and the documentation set (R21) under a license permitting course use and future student maintenance.

---

*Prepared for the capstone team by the project sponsor. The mission — and the probe — is named **Sojourn**: a long stay, far from home.*
