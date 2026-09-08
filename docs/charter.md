# Project Charter & Requirements — "Sojourn"
## A Reverse Engineering Game Platform (Software & Cybersecurity Capstone)

| | |
|---|---|
| **Document** | Project Charter and Requirements Specification |
| **Version** | 0.7 (Draft — one identifier per requirement: the introspection specification's I-numbers folded into R24.1–R24.21 and a generated register added. v0.6 — §6.11 ground-station console and session lifecycle requirements added; scenario-controlled telemetry decoding. v0.5 named QEMU as the emulation target and deferred Renode; emulation risk downgraded. v0.4 captured the specifications' normative content as requirements; §6.8–§6.10 added; R2.2, R3.1, R3.2, R21, R22.1 amended) |
| **Date** | September 3, 2026 |

---

## 1. Project Summary

The team will build a **reverse engineering game platform** in which a player takes the role of a mission operations engineer for an aging deep-space probe. The probe's source code has been lost; only the flight binary, a memory map, and partial "recovered" documentation survive. To keep the mission alive, the player must reverse engineer the ARM firmware and uplink commands that read and overwrite portions of probe memory — disabling failing subsystems, altering mission parameters, and eventually injecting new functionality — exactly as NASA has done for the Voyager probes.

The player experience is a tight feedback loop: analyze the binary offline in a disassembler, compose an uplink through a ground-station console, wait out a simulated transmission delay, and read the resulting downlink telemetry to learn whether the change took effect.

The capstone team builds the **platform**: an emulated probe, a command uplink/downlink protocol, a ground-station console, a scenario engine with live objective checking, and atleast **two polished reference scenario** proving the platform works. The platform will later serve as courseware for a reverse engineering course, so **extensibility is a first-class requirement**: adding a future mission must require authoring content, not modifying code.

## 2. Objectives & Success Criteria

The project succeeds if, at the end of the semester:

1. A student can be handed a container image, run it locally with one command, open the ground-station console in a browser, and play the reference scenario end to end with no instructor assistance.
2. The player receives **immediate, layered feedback** for every uplink: protocol ACK/NAK, observable telemetry changes, and objective status transitions — including partial-progress feedback.
3. The probe can be **bricked and recovered**: a destructive patch causes a watchdog reset to a protected golden image, observable in telemetry, without losing the player's saved progress.
4. A **new scenario can be authored without touching platform code**: the instructor demonstrates this by dropping a second scenario package (however small) into the content directory and playing it.
5. Player progress (completed objectives, command history) survives container restarts and image upgrades via a mounted volume.
6. All five components (firmware, emulation harness, game daemon, console, scenario format) are documented well enough that a future course team can maintain them.

## 3. Background & Motivating Example

In 2023–2024, NASA JPL revived Voyager 1 which was 15 billion km away, 22-hour one-way light time, by diagnosing a failed memory chip in the Flight Data Subsystem from garbled telemetry alone, then relocating and patching the affected code by poking new bytes into memory, section by section, with no ability to test on the real hardware first. Sensor shutdowns to conserve Voyager 2's power budget follow the same pattern: small, surgical, irreversible-feeling memory writes, verified only through downlink telemetry.

This project compresses that experience into a game: the same constraints (opaque binary, narrow uplink, telemetry-only feedback, real consequences for mistakes) at a scale a student can master in weeks rather than a career.

## 4. Player Experience 

> The player unpacks the mission archive: a container image, `probe.bin` (the flight firmware), a memory map, and the *Recovered Mission Operations Manual* an authentic-looking but incomplete documentation of the probe's subsystems, telemetry format, and command protocol. They start the container and open the ground-station console in a browser: a terminal-style interface showing a live downlink telemetry feed and an uplink command line.
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
        ▲ │   virtual UART (command protocol)  +  introspection (GDB remote serial protocol)
        │ ▼
Emulated Probe  (ARM Cortex-M firmware on QEMU · watchdog & golden image)

— all inside one container —
content: /scenarios/*  (drop-in packages)      mounted volume: /savedata  (saves, command log)
```

### 5.1 Probe Firmware 

Bare-metal C for **ARM Cortex-M (Thumb-2)**. Chosen deliberately: it is what Ghidra handles cleanly, it is simple to emulate, and it is authentic to real spacecraft-class embedded software. The reference firmware implements: a cooperative main loop, a sensor subsystem table (the primary patch target), a telemetry encoder emitting periodic downlink frames, a command interpreter (PEEK/POKE/CALL/status), a watchdog, and a protected golden-image recovery path. Firmware source is a *platform deliverable* (for future scenario authors) but is **never shipped to players**. Players get only the built binary, memory map, and manual.

### 5.2 Emulation Harness

Runs the firmware under **QEMU** (`-M mps2-an386`) with: a virtual UART carrying the command protocol, the GDB remote serial protocol stub the daemon reads memory through (§6.9), and watchdog/reset modeling. One probe instance per container — solo play is the design point. 


### 5.3 Game Daemon 

A local service that owns everything between the emulator and the browser: loads scenario packages; relays uplink frames to the probe (enforcing the scenario's transmission delay, bandwidth budget, and checksum rules); decodes nothing about the firmware itself. All firmware-specific knowledge lives in the scenario package; continuously evaluates objective assertions against emulator state and telemetry after each downlink cycle; appends every uplink to a persistent, timestamped **command log**; and writes save state. **Progress persistence is by command-log replay:** on restart, the daemon replays the logged uplinks against a fresh probe instance rather than snapshotting emulator memory. This makes saves trivially portable across image upgrades and gives command history, save/restore, and (future) grading evidence from a single mechanism.

### 5.4 Ground-Station Console 

Browser-based (xterm.js or equivalent), served by the daemon. Panels: live downlink telemetry feed (raw frames — decoding them is part of the game); uplink command line with history; transmission-delay countdown for in-flight commands; mission status panel (objectives with pending / partial / complete states and unlock-on-completion briefing text); and an event ticker (ACK/NAK, watchdog resets). Presentation should be diegetic — a mission-control console, not a quiz app.

### 5.5 Scenario Package Format 

A scenario is **pure content**: a directory (or archive) containing

- `manifest` — metadata, ordering/dependencies of objectives, delay/bandwidth parameters;
- `firmware.bin` + memory map — the probe image and its layout;
- `docs/` — the player-facing recovered manual (shipped verbatim);
- `objectives/` — one declarative entry per objective: briefing text, and **win conditions as machine-checkable assertions** over (a) memory state read via introspection and (b) telemetry field predicates, with optional **partial-progress states** carrying diagnostic hint text (e.g., "Sensor silenced but power draw unchanged. Did you stub the readout instead of cutting power?").

The assertion language is the platform's core abstraction. It must be expressive enough for the reference scenario's hardest objective (code injection) and simple enough that an instructor can author it from documentation alone. The acceptance test is objective #4 in §2: **a new scenario is added with zero platform-code changes.**

> **This format is specified, not delegated.** See the *Scenario Package Format* specification (`docs/scenario_format.md`), normative for the package layout, the manifest, the assertion vocabulary, the evaluation contract, the command-log format, and one thin daemon entry point used only for testing. It is deliberately silent about daemon architecture, language, storage and the console, which remain the team's design. It ships with two reference packages, a reference evaluator, a validator satisfying R13, and a conformance suite that serves as the daemon's acceptance gate. 

## 6. Requirements

**Convention.** **SHALL** denotes a binding, individually verifiable requirement. **WILL** denotes a statement of fact or sponsor intent requiring no verification. SHOULD/MAY do not appear in requirement statements; negotiability is captured in the Priority column. **Priority:** **T** = threshold (the project fails acceptance without it), **O** = objective (expected; negotiable under §9 schedule pressure), **S** = stretch. **Verify:** **I** = inspection, **A** = analysis, **D** = demonstration, **T** = test (automated).

**Sponsor-furnished items.** The sponsor WILL supply the reference flight firmware (golden image, memory map, instructor-side symbol map) before the semester begins, and WILL co-author the recovered manual and all scenario fiction. The platform WILL be evaluated against these requirements at the acceptance demonstration (§10).

### 6.1 Gameplay & Feedback

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R1.1 | T | The probe SHALL reply to every uplink frame delivered to its UART with `ACK` or `NAK <code>` within 2 s of delivery (simulated transmission delay excluded). | T |
| R1.2 | T | ACK/NAK replies SHALL encode command receipt and execution status only; no probe reply SHALL encode objective state. | I |
| R2.1 | T | The daemon SHALL re-evaluate every active objective assertion within one telemetry period of receiving each downlink frame. | T |
| R2.2 | T | Objective state SHALL be derived solely from introspected probe memory, decoded downlink telemetry, and the command log; the platform SHALL expose no player-accessible input that sets objective state directly. | I |
| R3.1 | T | Every objective SHALL be in exactly one of four states at all times: `locked`, `active`, `complete`, or `failed`. Diagnostic "partial" text is a property of an `active` objective and SHALL NOT be represented as a state. | T |
| R3.2 | T | Within 2 s of a partial condition first holding for an `active` objective, the console SHALL display that condition's scenario-authored diagnostic text, and SHALL clear it within 2 s of no partial condition holding. | D |
| R3.4 | T | The console SHALL reveal each authored hint once its objective has been `active` for the authored frame count, SHALL reveal hints cumulatively, and SHALL reveal no hint or brief for a `locked` objective. | D |
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
| R20.3 | T | The scenario conformance suite SHALL pass in full on every merge to the default branch, with zero failures across its validation and replay cases. | T |
| R21 | T | Delivery SHALL include exactly these documents: (a) the player quickstart; (b) the reference scenario's recovered manual; (c) the platform architecture & maintenance guide, produced by the team; and (d) the four sponsor-furnished specifications — Firmware Design, Scenario Package Format, Introspection API, and Scenario Author's Guide — carried forward at the revision delivered. | I |

### 6.7 Future-Proofing

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R22.1 | T | Each command-log entry SHALL contain: a monotonically increasing sequence number with no gaps; the **probe uptime in milliseconds at which the command was applied**, which is authoritative for replay; the raw uplink text verbatim; the budget resource charged, or null; and the probe's reply verbatim. A wall-clock timestamp MAY additionally be recorded for human reading and SHALL NOT be used to schedule replay. | T |
| R22.2 | O | The command-log format SHALL be versioned and documented such that an instructor-side replay verifier can be built with no platform changes, confirmed by analysis at the design review. | A |

### 6.8 Scenario Package & Content Seam

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R23.1 | T | The daemon SHALL load only packages conforming to the Scenario Package Format at the format revision it implements, and SHALL refuse any package declaring a higher `format` value, reporting the package path and the unsupported value. | T |
| R23.2 | T | The daemon SHALL ignore unrecognized keys at every level of a package rather than refusing it, so that a package authored against a later revision of the format loads without platform change. | T |
| R23.3 | T | Within 10 s of session start the daemon SHALL compare the application-image CRC32 reported by the probe at boot against the package's declared `app_crc32`, and on mismatch SHALL refuse to start the scenario and report both values. | T |
| R23.4 | T | Scenario assertions SHALL address probe memory by symbol name resolved through the package's symbol map, or by absolute address only for peripheral register blocks; every resolved address and range SHALL fall inside a region declared in the package's memory map. | T |
| R23.5 | T | A package containing executable predicate code SHALL declare itself impure; the daemon SHALL provide a mode that refuses impure packages, and that mode SHALL be the default for any packaged distribution. | T |
| R23.6 | T | Every scenario package delivered with the platform SHALL be pure content, containing no executable predicate code. | I |
| R23.7 | T | The daemon SHALL expose a non-interactive entry point that accepts a scenario directory and a command log, replays the log, and emits final objective states as JSON, per the format specification's conformance interface. | T |
| R23.8 | T | Package setup writes SHALL be applied before the first evaluated frame, SHALL NOT be charged to any command budget, and SHALL NOT appear in the command log. | T |
| R23.9 | T | Objectives SHALL be evaluated in the order declared by the package, and within each objective in the order: failure condition, partial conditions, success condition. | T |
| R23.10 | T | A predicate over absent telemetry — an absent channel, an undefined field path, or a frame failing CRC — SHALL evaluate false and SHALL NOT abort the evaluation pass. | T |

### 6.9 Evaluation Integrity & Introspection

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R24.1 | T | The platform SHALL maintain exactly two connections to the probe: a command channel carrying only player-originated uplinks, and a read-only introspection channel used only for objective evaluation. | I |
| R24.2 | T | The daemon SHALL originate no uplink command of its own. Every command delivered to the probe SHALL correspond to exactly one player action recorded in the command log. | T |
| R24.3 | T | The daemon SHALL NOT write probe memory or registers over the introspection channel. | I |
| R24.4 | T | Introspection activity SHALL NOT be charged to any command budget, SHALL NOT be appended to the command log, and SHALL NOT alter any value observable in downlink telemetry. | T |
| R24.5 | T | The daemon SHALL use only these GDB remote serial protocol packets: query halt reason, read memory, negotiate supported features, continue, detach, and the raw interrupt byte. | I |
| R24.6 | T | The daemon SHALL NOT send write-memory, write-register, breakpoint, watchpoint, single-step or kill packets. Each either mutates the probe or alters its timing, and a breakpoint left set changes execution timing for the remainder of the session while being invisible in the command log. | I |
| R24.7 | T | The daemon SHALL decode run-length encoding in received packet data, in which an asterisk is followed by one character whose value less 29 is the count of additional repeats of the preceding character. | T |
| R24.8 | T | The daemon SHALL treat a reply beginning with the error prefix as a failed read and SHALL NOT interpret its characters as data. | T |
| R24.9 | T | The daemon SHALL honor the maximum packet size the stub advertises, SHALL split any longer read into chunks of at most 1024 bytes, and SHALL reassemble them in order. | T |
| R24.10 | T | For each downlink frame the daemon SHALL, in this order: decode the frame; compute its event list; apply any uplink whose delay has expired; halt the guest; perform every memory read the pass requires; resume the guest; then evaluate objectives. | T |
| R24.11 | T | All memory reads within one evaluation pass SHALL observe probe state at a single instant. | T |
| R24.12 | T | The daemon SHALL cache reads within one evaluation pass so that a repeated address and length is fetched once, and SHALL NOT cache reads across passes. | T |
| R24.13 | T | The snapshot window SHALL NOT exceed 250 ms, and exceeding it SHALL be treated as an error rather than leaving the probe halted. | T |
| R24.14 | T | A predicate over absent telemetry — an absent channel, an undefined field path, or a frame failing CRC — SHALL evaluate false and SHALL NOT abort the evaluation pass. | T |
| R24.15 | T | A failed introspection read — connection refused, timeout, error reply, or short read — SHALL abort the evaluation pass and leave every objective state unchanged; it SHALL NOT be evaluated as a false predicate. | T |
| R24.16 | T | On loss of the introspection channel the daemon SHALL attempt reconnection before the next evaluation pass, and SHALL report degraded grading to the console within one telemetry period if reconnection fails. | D |
| R24.17 | T | The daemon SHALL contain no emulator-specific introspection code; substituting the harness-tier emulator SHALL require configuration change only, verified by an empty diff across daemon source. | I |
| R24.18 | T | The emulator SHALL bind the introspection port to the loopback interface only. | I |
| R24.19 | T | The introspection channel SHALL NOT be documented in any player-facing material and SHALL NOT be reachable from the console. | I |
| R24.20 | T | No instructor-only data, the symbol map above all, SHALL be reachable through the introspection channel or present in the player image. | I |
| R24.21 | T | Objective evaluation SHALL be a pure function of setup state, the command log, and probe behavior. No objective state SHALL depend on wall-clock time, host performance, or a random source. Verified by replaying one command log of at least 20 commands twice and obtaining identical objective states and identical first-completion frame numbers. | T |

### 6.10 Traceability

**This charter is the requirements register.** Every requirement has exactly one identifier, defined here. The specifications explain, measure and justify those requirements; **none of them defines identifiers of its own**. Where a specification and this charter disagree, this charter governs and the specification is amended.

`requirements.md` is the whole set in one sorted table, generated from this document by `firmware/tools/requirements.py`; `requirements.csv` is the same data for a spreadsheet. Run `requirements.py --check` in CI: it fails if a requirement is defined twice, if one carries no SHALL, if a specification cites an identifier this charter does not define, or if a specification introduces its own numbering scheme.

Four specifications carry normative detail.

| Specification | Standing | Made binding by |
|---|---|---|
| Firmware Design Specification | Normative — the probe | R1.1, R1.2, R5.1–R5.3, R8.1, R8.2, R10.1, R10.2 |
| Scenario Package Format | Normative — the content seam | R11.1–R11.3, R13, R22.1, R23.1–R23.10 |
| Introspection API | Normative — evaluation transport | R2.2, R24.1–R24.21 |
| Scenario Author's Guide | Normative — authoring practice | R9.1, R9.2, R12 |
| Platform Design | **Advisory only** — carries no requirements | — |

Automated verification is concentrated in three suites, and a requirement marked **T** is expected to be covered by one of them:

| Suite | Covers |
|---|---|
| Firmware end-to-end (`firmware/tools/e2e_test.py`, 99 checks) | R1.1, R1.2, R5.1–R5.3, R10.2 |
| Scenario conformance (`conformance/run_conformance.py`, 18 checks) | R13, R23.1, R23.4, R23.7, R23.8, R24.4, R24.21 |
| Daemon unit and integration tests (team-authored) | R2.1, R3.1–R3.4, R4.1, R4.2, R4.3, R11.1, R14.1, R15.1, R15.2, R20.1, R23.2, R23.3, R23.5, R23.9, R23.10, R24.10–R24.16, R25.1–R26.7 |

Requirements verified by inspection, analysis or demonstration are settled at the design review (§10) rather than in CI, and are listed in the acceptance script.


### 6.11 Ground-Station Console

The console is the whole of the player's contact with the mission. §6.1 already governs feedback timing; this section governs what is on screen, and what the player can do to a running session.

**Layout and panels**

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R25.1 | T | The console SHALL present five regions simultaneously and without navigation: spacecraft read-out, downlink frame feed, uplink terminal, mission status, and ground-station link status. | D |
| R25.2 | T | The downlink feed SHALL display every received frame as transmitted, in hexadecimal, in arrival order, retaining at least the most recent 200 frames, and SHALL mark any frame failing CRC as corrupt without discarding it. | D |
| R25.3 | T | The spacecraft read-out SHALL present decoded values **only** for channels the active scenario package lists in `console.decode`; every other channel SHALL appear in the downlink feed as raw hexadecimal only. | T |
| R25.4 | T | When a decoded channel leaves the downlink, the read-out SHALL mark it absent within one telemetry period and SHALL NOT continue to display its last value. | T |
| R25.5 | T | The uplink terminal SHALL accept typed commands, maintain a recallable history of at least the most recent 500 commands per player across sessions, and display for each command in flight its remaining transmission delay to a resolution of 1 s. | D |
| R25.6 | T | The console SHALL display remaining write and read allowance whenever the active scenario declares a budget, and SHALL indicate a command refused for budget distinctly from a command the probe rejected. | D |
| R25.7 | T | The mission status panel SHALL render objectives in the order declared by the package, showing state, brief text for `active` and `complete` objectives, current partial diagnostic text, and revealed hints — and SHALL reveal neither brief nor hints for a `locked` objective. | D |

**Ground-station link visualization**

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R25.8 | T | The link panel SHALL identify the Deep Space Network complex currently holding the link, name the specific antenna carrying it, and animate signal activity distinctly for downlink reception and for an uplink in flight. | D |
| R25.9 | T | The complex in contact SHALL be derived from probe uptime unless the scenario pins one, so that a replayed session displays the same station sequence as the original. | T |
| R25.10 | T | The link panel SHALL display the one-way transmission delay in force and the spacecraft antenna in use, and SHALL indicate loss of link within one telemetry period of the probe ceasing to transmit. | D |
| R25.11 | O | Antenna selection within a complex SHALL reflect the spacecraft antenna in use, a larger aperture being shown for the high-gain link than for the low-gain link. | D |

**Session lifecycle**

| ID | Pri | Requirement | Verify |
|---|---|---|---|
| R26.1 | T | The console SHALL provide a menu offering, at minimum: start a scenario, abort the running scenario, save the session, load a saved session, and exit. | D |
| R26.2 | T | Starting a scenario while one is running SHALL require an explicit confirmation, and SHALL abort the running session before the new one begins. | D |
| R26.3 | T | Aborting a running scenario SHALL terminate the probe process and release its ports within 10 s, SHALL preserve the command log in full, and SHALL leave the session resumable. | T |
| R26.4 | T | Save SHALL write a portable session archive containing the command log, the scenario identifier and revision, and the player profile, and SHALL NOT require the scenario to be stopped. | T |
| R26.5 | T | Load SHALL restore a session from such an archive by replay (R15.1), SHALL refuse an archive whose scenario identifier is not installed, and SHALL warn when the installed revision is higher than the archive's. | T |
| R26.6 | T | Exit SHALL terminate the probe process, flush the command log, and leave no orphaned emulator process, verified by process inspection after exit. | T |
| R26.7 | T | No menu action SHALL be able to alter objective state other than by replaying a command log. | I |



Final acceptance is a live demonstration by the instructor, unassisted, of: pulling the image, playing the reference scenario's first two objectives, deliberately bricking the probe and recovering, restarting the container and confirming restored progress, and installing the second mini-scenario by copying a directory. Handoff includes all repositories, the container build pipeline, and the documentation set (R21) under a license permitting course use and future student maintenance.

---
