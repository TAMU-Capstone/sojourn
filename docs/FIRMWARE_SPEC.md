# Probe Flight Firmware — Design Specification

| | |
|---|---|
| **Document** | Golden-Image Flight Firmware, Engineering Design Specification |
| **Project** | "Sojourn" Reverse Engineering Game Platform |
| **Version** | 0.9 (Draft — comms/antenna subsystem; 96×96 scenes; §15 down to one open item) |
| **Date** | August 26, 2026 |
| **Authors** | Trevor Bakker (sponsor) with Claude |
| **Audience** | Instructor and capstone team. **This document is not player-facing** — the player-facing *Recovered Mission Operations Manual* is derived from it with deliberate omissions (§14). |

---

## 1. Purpose & Scope

This specifies the **instructor-supplied reference firmware**: a working, bootable flight program for the emulated probe, handed to the capstone team on day one as their golden image. Run under QEMU or Renode, it boots, simulates active sensors, emits downlink telemetry, and answers uplink commands — before any platform code exists. The team builds the game platform *around* it.

The spec covers the firmware proper, its memory map, its two-tier sensor simulation, its command and telemetry interfaces, and the toolchain that builds and runs it. Scenario content (objectives, fiction, the recovered manual's exact text) is out of scope here except where the firmware must provide hooks for it.

## 2. Design Constraints (imposed by the game)

The firmware is a game board disguised as flight software. Every design choice below serves one of these constraints:

- **C1 — Patchable in flight.** Application code must execute from RAM so `POKE` can modify code, not just data. (Real precedent: Voyager's FDS executes from patchable memory.)
- **C2 — Brickable and recoverable.** A destructive patch must be able to hang the probe, and a watchdog must restore a pristine image without player intervention, observably (reboot counter, uptime reset).
- **C3 — Analyzable in stock Ghidra.** ARM Thumb-2, conventional layout, no obfuscation. Difficulty comes from scale and missing documentation, never from anti-analysis tricks.
- **C4 — Observable effects.** Every meaningful state change must surface in telemetry or be readable by the daemon via the introspection channel, so objectives verify effects rather than methods.
- **C5 — Multiple valid solutions.** Key behaviors (e.g., a sensor contributing to telemetry) must depend on more than one patchable point, so different attack strategies all work — and can be distinguished for partial-progress feedback.
- **C6 — Content seam.** Firmware-specific knowledge (addresses, formats) must live in the scenario package, not in platform code. The firmware build must emit machine-readable artifacts (symbol map, memory map) for scenario authoring.

## 3. Target Platform & Toolchain

| Item | Choice | Rationale |
|---|---|---|
| CPU core | ARM Cortex-M4 (no FPU dependence) | Thumb-2 only; Ghidra-clean; spacecraft-class; QEMU & Renode both model it |
| Primary emulator | QEMU `-M mps2-an386` | Ships in stock QEMU; Cortex-M4; simple CMSDK UART |
| Fallback emulator | QEMU `-M lm3s6965evb` (Cortex-M3) | Ubiquitous, extremely well documented; build flag switches UART driver |
| End-state emulator | Renode, custom `.repl` platform | Scripted Python peripherals for harness-tier sensors (§6) |
| Toolchain | `arm-none-eabi-gcc`, `-mthumb -Os`, GNU LD scripts, `objcopy` | Standard, free, reproducible |
| Languages | C11 + a few lines of startup assembly | Team-readable; Ghidra decompiles it well |
| Debug/introspection | GDB remote serial protocol (`-gdb tcp::3333`) / Renode monitor | The daemon's window into memory & registers |

UART base addresses differ per machine (CMSDK UART0 at `0x40004000` on MPS2; PL011 at `0x4000C000` on LM3S) — the HAL isolates this behind `board.h`, and exact register offsets are confirmed at bring-up, not trusted from this document.

## 4. Memory Map

Logical layout, enforced by linker scripts and by the `POKE` handler's protection table. Addresses are the specification; emulator RAM sizing must simply cover them.

| Region | Range | Size | Contents | POKE |
|---|---|---|---|---|
| ROM | `0x0000_0000 – 0x0000_03FF` | 1 KiB | Boot vector table | refused (`E04 PROT`) |
| ROM | `0x0000_0400 – 0x0000_3FFF` | 15 KiB | Bootloader + ROM services (§5) | refused |
| ROM | `0x0000_4000 – 0x0002_3FFF` | 128 KiB | **Golden application image** + CRC32 trailer | refused |
| ROM | `0x0002_4000 – 0x0002_FFFF` | 48 KiB | **Detector image store** — 5 × 96×96 stored scenes (45 KiB used), outside the app image so the player's binary holds no pixels (§6.4a) | refused |
| SRAM | `0x2000_0000 – 0x2000_00FF` | 256 B | NOINIT persistent block: reboot counter, last-fault code (survives watchdog reset) | refused |
| SRAM | `0x2000_0100 – 0x2000_0FFF` | 3.75 KiB | Bootloader/system data, watchdog counter | refused |
| SRAM | `0x2000_1000 – 0x2001_8FFF` | 96 KiB | **APP region**: application code + rodata, copied from golden image at boot, executes in place | writable |
| SRAM | `0x2001_9000 – 0x2001_CFFF` | 16 KiB | App `.data`/`.bss`, heap, incl. task table (§7) | writable |
| SRAM | `0x2001_D000 – 0x2001_DFFF` | 4 KiB | **Code cave** — undocumented landing zone for injected instructions; 32 × 128 B slots (§6.5) | writable |
| SRAM | `0x2001_E000 – 0x2001_EFFF` | 4 KiB | **Sensor register block** (SIM tier, §6) | writable* |
| SRAM | `0x2001_F000 – 0x2001_FFFF` | 4 KiB | Stacks (main + handler) | writable |
| SRAM | `0x2002_0000 – 0x2002_23FF` | 9 KiB | **CAM frame buffer** — most recent image, raw 96×96 8-bit grayscale (§6.1) | writable |

*Writable by design: poking a sensor's CTRL register is a legitimate solution path (C5). In the harness tier this block becomes true MMIO at the same addresses.

Everything a player can brick is restored at reset (the APP copy, data, stacks); everything that must survive a brick is protected (ROM, NOINIT, system block). The protection table itself lives in ROM.

## 5. Boot Sequence & Golden-Image Recovery

1. **Reset** (power-on or watchdog). Core fetches SP/PC from the ROM vector table; bootloader runs.
2. Bootloader increments the **reboot counter** and records the pending fault code in NOINIT.
3. Bootloader **copies the golden application image from ROM to the APP region** — unconditionally, every boot. Recovery is not a special case; it is the only case. (CRC32 check of ROM image is a sanity assertion, not a recovery branch.)
4. Bootloader initializes SysTick and the watchdog service (§10), sets `VTOR` to the application vector table at `0x2000_1000`, and jumps to the application entry point.
5. Application enters `MODE_BOOT`, runs self-init (sensor block bring-up, task table init), and transitions to `MODE_NOMINAL`. First telemetry frame is on the wire within one telemetry period.

Consequences for gameplay: a watchdog reset silently discards **all** player patches (they were in RAM), while the reboot counter and fault code — visible in the next telemetry frame — tell the player exactly what happened. Re-applying patches from command history is intended workflow, which is why the daemon, not the probe, owns command logging.

## 6. Sensor Subsystem — Two Tiers, One Interface

The firmware sees sensors only through a fixed **register block** (base `0x2001_E000`): 8 slots × 16 bytes.

| Offset | Register | Meaning |
|---|---|---|
| +0x00 | `CTRL` (u32) | bit0 `POWER` (1 = powered). Other bits reserved. |
| +0x04 | `STATUS` (u32) | bit0 `READY` (data valid), bit1 `FAULT` (degraded/failing) |
| +0x08 | `DATA` (s32) | Latest reading, sensor-specific units |
| +0x0C | `POWER_MW` (u32) | Current draw in mW (0 when unpowered) |

| Slot | ID | Sensor | Nominal behavior (SIM tier) |
|---|---|---|---|
| 0 | `MAG` | Magnetometer | Slow sinusoidal field + noise; scripted degradation raises `FAULT`, noise floor, and power draw |
| 1 | `IMU` | Inertial unit | Small random-walk rates |
| 2 | `THM` | Thermal | Slow drift correlated with total power draw |
| 3 | `PWR` | Bus monitor | Bus mV ≈ constant; mA tracks sum of sensor `POWER_MW` |
| 4 | `RAD` | Radiation counter | Poisson-ish counts; occasional bursts |
| 5 | `STR` | Star tracker | Attitude quaternion component; high power cost |
| 6 | `CAM` | Imaging camera | Power/status/draw for the imaging subsystem; full control interface in §6.1 |
| 7 | — | Empty slot | `READY=0`; reserved for future scenarios |

**SIM tier (prototype, plain QEMU).** A `physics_tick` task inside the firmware updates the block each cycle: deterministic xorshift PRNG (seeded from a ROM constant, so runs are reproducible), baselines, drift, noise, and power accounting. Behind the `sensor_read()`/HAL seam, nothing else in the firmware knows the physics is onboard. A player in Ghidra *can* find the physics code — that is acceptable and even instructive for the prototype; it is compiled to be unremarkable.

**Harness tier (end state, Renode).** The register block becomes memory-mapped peripherals implemented as Renode Python peripherals at the same addresses; `physics_tick` is compiled out (build flag `SENSOR_TIER=HW`). Physics, degradation schedules, and fault injection move into the scenario package as harness scripts — invisible to disassembly and controllable per scenario. **The register layout above is the contract that makes the two tiers swappable.**

Sensor participation in telemetry requires **two** independent conditions (C5): the slot's `CTRL.POWER` bit is set, **and** the application's polling entry for that sensor is enabled in the task/polling table (§7). Cutting power saves watts and empties the channel; disabling polling empties the channel but leaves the draw — the classic partial-progress distinction the scenario exploits.

### 6.1 Imaging Subsystem (CAM)

The camera is deliberately richer than the simple sensors: it is the **parameter-rich subsystem** that powers "change the target," "fix the exposure," and "downlink an image" missions. Its power/status/draw live in sensor slot 6 like any other sensor; its control interface is an **extended register block** at `0x2001_E100` (64 bytes):

| Offset | Register | Meaning |
|---|---|---|
| +0x00 | `CCTRL` (u32) | bit0 `CAPTURE_NOW` (one-shot, self-clearing), bit1 `AUTO` (scheduled captures) |
| +0x04 | `CSTAT` (u32) | bit0 `READY`, bit1 `BUSY`, bit2 `POINT_ERR` (no attitude reference) |
| +0x08 | `TARGET` (u32) | Index into the target catalog (config block) |
| +0x0C | `EXPOSURE_MS` (u32) | Exposure time, 1–10 000 ms |
| +0x10 | `GAIN` (u16) + `BINNING` (u16) | Analog gain; pixel binning factor |
| +0x14 | `FRAME_ID` (u32) | Increments on every completed capture |
| +0x18 | `FRAME_ADDR` (u32) + `FRAME_LEN` (u32) | Location and size of the latest frame (the frame buffer, §4) |
| +0x20 | `HIST_MEAN`, `HIST_MAX`, `SAT_PCT`, `STARS` (4 × u32) | Post-capture statistics: mean and peak brightness, % saturated pixels, star-detection count |

**Target catalog.** An array in the app config block — `{RA u16, DEC s16, magnitude u8, flags u8}` per entry. Retargeting has two honest solutions (C5): patch the `TARGET` index, or patch the catalog entry it points at.

**Image synthesis.** Captures are deterministic in `(target, exposure, gain, binning)`. SIM tier: a procedural star field — star positions drawn from the PRNG seeded by the catalog entry, pixel brightness scaled by exposure × gain, clipping into saturation when overexposed; `STARS` counts above-threshold detections. Harness tier: a Renode peripheral renders the frame and writes the buffer over the same register contract. Either way the statistics registers are computed from the actual pixels, so exposure objectives are verifiable from telemetry alone: an overexposed frame shows high `SAT_PCT` and few `STARS`; a corrected one shows the reverse.

**Capture paths.** A `cam_capture` task in the task table (§7) services `AUTO` mode; `CAPTURE_NOW` gives one-shots. Capturing requires an attitude reference — star-tracker lock or the sun-sensor fallback — otherwise `CSTAT.POINT_ERR` is raised and the frame is not taken: a deliberate cross-subsystem dependency (power down `STR` carelessly and imaging objectives start failing).

**Image downlink.** Pixels never ride in telemetry — only the stats channel (§9). Recovering an actual image means `PEEK`-dumping the 4 KiB frame buffer, 64 bytes per command, under the uplink budget — the same slow, deliberate pain as a real deep-space image downlink. The ground-station console may reassemble dumped frames into a viewable image (a platform/frontend feature, not a firmware one). Whether to later add a bulk `DUMP` verb is a scenario-difficulty decision (§15).

### 6.4 Auxiliary Flight Functions (scenario surface bank)

Beyond the science payload, the firmware carries a set of **plausible housekeeping functions** whose only job is to be raw material for future scenarios. Each is a task in the scheduler (§7), driven entirely by values in the config block, gated by a simple enable/threshold branch, and observable in the housekeeping telemetry channel (§9, `0x60`). Their defaults keep the probe healthy as built; a scenario shifts one threshold or clears one enable to manufacture the fault it is about. Every one therefore supports all four patch styles — data patch (a threshold), code patch (a comparison/branch), task-table disable, and verification-by-telemetry.

| Function | Task | Behavior | Example scenario hooks |
|---|---|---|---|
| **Thermal control** | `task_heater` | Hysteretic thermostat on `THM`; adds `heater_draw_mw` to the bus load while heating | Raise the setpoint so the heater runs and drains the budget; disable it and let the probe run cold |
| **Power management** | `task_power_mgr` | Sheds the lowest-priority powered subsystem when load exceeds `power_budget_mw` | Lower the budget so it sheds a science sensor mid-mission; the player must raise the budget, disable shedding, or re-order the shed-priority table to keep a sensor alive |
| **Attitude control** | `task_acs` | Accrues momentum each cycle; desaturates at `acs_momentum_max`, spending propellant; saturates (sticks) when propellant is gone | Stuck reaction wheel; propellant conservation (disable ACS); the privileged `TRIM` command (§8) |
| **Data recorder** | `task_recorder` | Fills with science data per active sensor, drains at `rec_downlink_rate`; caps at `rec_buffer_max` | Buffer overflow / data loss when downlink is disabled or generation is spiked |

The config block (§7) holds every tunable — setpoints, budgets, rates, momentum limits, propellant load, and the engineering-command key (§8). All of it lives in patchable working memory. Defaults: heater setpoint 10.0 °C (off in nominal warmth), power budget 5000 mW (no shedding), ACS on with 8000 mg propellant, recorder draining faster than it fills.

### 6.4a Stored Scenes and the Imaging Pipeline

The camera does not synthesize pixels. Each catalog target carries a **scene index** selecting one of `SCENE_COUNT` stored 96×96 8-bit grayscale images. The camera reads that scene, runs it through the pipeline below, and **writes the result into the frame buffer** — which is what the ground downlinks.

**Where the source images live — and why not in the player's binary.** The scenes are *not* part of the application. They occupy a **detector image store** in ROM at a fixed address (`0x0002_4000`) deliberately placed **outside the golden application image**, and the app reaches them through `SCENE_AT(i)`. The player receives `probe_app.bin`, which therefore contains **no pixels at all** — only the code that reads an address. Verified by the build: moving the scenes cut the player binary from 21,532 to 5,191 bytes, and a byte-search for scene data in it fails.

A player can still obtain the source, but only by earning it: find the store address in the disassembly and `PEEK`-dump ROM at 64 bytes per command (64 commands per scene, against the uplink budget). That is a legitimate and expensive act of reverse engineering, which is the right way to discover an easter egg. If a scenario wants the source strictly unreachable, the command interpreter's `readable()` window can exclude the store — and in the Renode harness tier (§6) the detector becomes a scripted peripheral, so the imagery never exists in the firmware at all and authors can swap it without rebuilding.

| Scene | Subject | Origin |
|---|---|---|
| 0 | Survey field K-25 | procedural star field |
| 1 | 1 Ceres, Occator bright spots | NASA/JPL-Caltech (Dawn), public domain |
| 2 | Saturn north polar vortex and rings | NASA/JPL-Caltech (Cassini), public domain |
| 3 | Mimas, Herschel crater — **easter egg** | NASA/JPL-Caltech (Cassini), public domain |

**The easter egg.** Scene 3 is *not referenced by any catalog entry*, so it cannot be commanded. Roughly **1 capture in 100** returns it instead of the commanded target: a Cassini image of Mimas, the Saturnian moon whose 130 km Herschel crater gives it a famously Death-Star-like silhouette. The roll is advanced per capture from a fixed seed rather than from the clock, so it is **replay-deterministic** — essential, because the platform's saves are command-log replays (charter R15.1) and a truly random egg would make a replayed log diverge. `g_cam_egg_pct` controls the rate: `0` disables it, `100` forces it, which is how the regression test verifies the scene exists.

> **Why raw pixels rather than a stored JPEG/PNG.** A compressed image cannot be meaningfully inverted or filtered by poking bytes, and an on-board decoder would be a large block of un-patchable code. Real missions downlink raw sensor data and form image products on the ground, so the probe holds raw pixels and the *ground station* writes the PNG (`tools/img_recover.py`). That keeps every stage of the pipeline a legitimate patch target.

Pipeline, source → frame buffer, in order:

| Stage | Surface | Ships as | Patch difficulty |
|---|---|---|---|
| Convolution | `cam_kernel[9]` + `cam_kdiv` | identity kernel | data — blur, sharpen, edge-detect are coefficient changes |
| Exposure / gain | `EXPOSURE_MS`, `GAIN` registers | 250 ms, ×16 | data — already the over/under-exposure objective (§6.1) |
| Transfer curve | `cam_lut[256]` | identity ramp | **data — the inversion objective: 8 uplinks rewrite the curve** |
| Stage selection | `cam_filter` (config) | `FILT_LUT` | data — enable/disable stages |
| The loop itself | `image_process()` | — | code — has an entry pad and an inline patch point (§6.5) |

The LUT stage is **live but invisible as built**: it ships as an identity ramp, so the pipeline already runs it and a scenario needs only to rewrite 256 bytes to invert, threshold, posterize or solarize the downlinked image. Because the LUT is applied last and the statistics are computed from the frame buffer, an inversion is verifiable **from telemetry alone** — the dark sky becomes bright, so `HIST_MEAN` jumps — without downlinking a single pixel.

Capture statistics are computed from the written frame, not the source. `STARS` counts bright *unclipped local maxima*, so it measures genuine point sources: an overexposed frame is a flat bright field and scores near zero, while a merely bright frame does not inflate the count.

**Recovering the picture.** Pixels never ride in telemetry. `tools/img_recover.py` drives the documented downlink — `PEEK` the frame buffer 64 bytes at a time, 64 commands for a full frame — and writes a PNG with a dependency-free encoder (`tools/png.py`, stdlib only). Every action it takes is an ordinary uplink a player could type by hand, including `--invert`, `--threshold`, `--filter blur|sharpen|edge` and `--target N`.

### 6.4b Downlink Comms: Antenna Failure and Bandwidth Triage

Real precedent: **Galileo's** high-gain antenna failed to unfurl in 1991, and the mission was saved by reprogramming the spacecraft in flight to run science through the low-gain antenna — new compression, and hard decisions about which data was worth the bandwidth. `comms.c` is that scenario in miniature.

Sojourn downlinks through one of two antennas. The high gain carries the whole telemetry frame (`hga_max_payload`, 96 bytes as built); the low gain carries a fraction (`lga_max_payload`, 40 bytes), which is less than the frame needs. When the high gain is declared failed, `task_comms` falls back to the low gain and the telemetry encoder begins **emitting channels in the order given by `tlm_priority[]` until the budget is exhausted**, dropping the rest and reporting the count.

Nothing is truncated — a partial channel would corrupt the frame — so the squeeze is felt as whole channels disappearing, which the ground sees immediately in the new `COMMS` channel (`0x61`: antenna, dropped count, current budget). The encoder decides what fits *before* it emits, so that count describes the frame carrying it rather than the previous one.

Every response a real flight team could make is a patch:

| Response | Surface |
|---|---|
| Decide what science is worth the bandwidth | `tlm_priority[]` — the emission order, a byte array in RAM. *This is the Galileo decision.* |
| Dispute the fault verdict | `g_hga_ok`, or the branch in `task_comms` that acts on it |
| Cancel the scheduled failure | `hga_fail_after_s` in the config block |
| Argue with the physics | `lga_max_payload` |
| Make room by other means | power down sensors, so their channels stop competing |

As built the high gain is healthy and `hga_fail_after_s` is `0` (never), so a scenario schedules the failure. Because the fallback is re-evaluated every cycle, clearing the verdict restores the high gain — the fault is a *judgement the software makes*, not a latched state, which is what makes it patchable.

### 6.5 In-Flight Patching: Pads, Cave, and Trampolines

The hardest constraint in real spacecraft maintenance is that **the fix rarely fits where the bug is**. Voyager's 2024 recovery was exactly this: the affected code had to be relocated elsewhere in memory because there was no room to repair it in place. The firmware therefore ships with pre-planted space so a player can *detour* — jump out of a function into spare memory, run new instructions, and return into the original body.

**Why pre-planted space matters.** The naive detour overwrites real instructions, which then have to be relocated ("stolen") into the cave. On ARM that is genuinely hazardous: any PC-relative operand (`LDR` literal, `ADR`, `B`/`BL`, anything reading `PC`) silently computes a different address once moved. By overwriting only padding, nothing needs relocation, and the technique becomes teachable before it becomes hard.

Three mechanisms, all in patchable RAM:

| Mechanism | Where | Size | Use |
|---|---|---|---|
| **Entry pad** (`PATCH_ENTRY`) | First bytes of every scheduled task, ahead of its compiler prologue | 8 B (4 NOPs) | Hook the whole function: jump out, do work, return to `<func>+8` and the original body runs untouched |
| **Inline patch point** (`PATCH_POINT()`) | Immediately before a decision inside a body (thermostat test, power-budget test, desat test, recorder balance, safe-mode trip) | 8 B (4 NOPs) | Alter one branch rather than the whole function |
| **Code cave** | Free RAM `0x2001_D000`–`0x2001_DFFF` | 4 KiB = 32 × 128 B slots | Where the new instructions live |

Both pads are produced by the compiler (`-fpatchable-function-entry` via attribute, and a volatile NOP sled), so the symbol for a padded function points at the **first NOP** — the patch site is simply `<func>+0`, and the resume point is `<func>+8`.

**The jump idiom.** An 8-byte absolute branch that needs no offset arithmetic (the target word must carry the Thumb bit):

```
DF F8 00 F0     LDR.W PC, [PC, #0]
<target|1>      .word
```

**Worked example** (this is the automated regression test in `tools/e2e_test.py`, run on every build). Hook `task_acs`, set a sentinel, then fall back into the real function:

```
; --- in the cave at 0x2001D000 ---
48 02   LDR  R0,[PC,#8]      -> &g_shed_count
21 2A   MOVS R1,#42
70 01   STRB R1,[R0]
4A 02   LDR  R2,[PC,#8]      -> resume address
47 10   BX   R2
BF 00   NOP                  ; align the literals
<&g_shed_count>              ; +12
<(task_acs+8)|1>             ; +16

; --- over the 8-byte entry pad of task_acs ---
DF F8 00 F0  <0x2001D000|1>
```

Two uplinks install it. Telemetry then shows the sentinel (proving the hook ran) while momentum keeps advancing (proving control returned into the original body).

**Difficulty ladder.** The pads make the technique approachable, and removing them makes it authentic — a scenario can escalate deliberately:

1. *Easiest* — no assembly at all: repoint a task-table `handler` at a routine written into the cave.
2. *Moderate* — the pad detour above: overwrite only NOPs, resume at `+8`.
3. *Hard* — patch a function with no pad: overwrite real instructions, relocate the stolen ones into the cave, and resume mid-function. This is where PC-relative operands must be recognized and rewritten, and where a mistake earns a watchdog reset (§10) rather than a corrupted mission.

## 7. Application Structure — Cooperative Scheduler

The application is a single-threaded cooperative loop over a **task table** in app data (found, not documented):

| Field | Type | Notes |
|---|---|---|
| `handler` | function pointer | `NULL` = empty slot, skipped |
| `period` | u32 ticks | 0 = every cycle |
| `countdown` | u32 | Decremented per tick |
| `flags` | u32 | bit0 `ENABLED` |

Shipped tasks: `cmd_process` (§8), `physics_tick` (SIM tier only), `sensor_poll` (reads register block per polling config), `wdg_pet` (§10), `fault_monitor` (raises `SAFE` mode on persistent sensor faults), `camera` (§6.1), `telemetry_send` (§9), and the four auxiliary flight functions of §6.4 (`heater`, `power_mgr`, `acs`, `recorder`). The table ships with **two empty slots** at the end. The intended (never required) path for the code-injection objective: write a routine into free RAM, then `POKE` a handler pointer and flags into an empty slot. The main loop validates nothing — a bad pointer hard-faults, the watchdog fires, and the probe recovers (C2).

A **config block** in app data holds every tunable: telemetry period, safe-mode thresholds, camera defaults, the target catalog, all §6.4 function parameters, and the engineering-command key. It is the primary target surface for "change mission parameters" objectives, and it lives entirely in patchable working memory.

## 8. Uplink Command Protocol (UART, line-based)

Format: `VERB [args] *CCCC` — ASCII, space-delimited, terminated `\n`, where `CCCC` is CRC-16/CCITT (hex) over everything before the `*`. Addresses and bytes in hex.

| Verb | Args | Action | Reply |
|---|---|---|---|
| `PING` | — | Liveness | `ACK PING` |
| `PEEK` | addr len (≤64) | Read memory | `ACK PEEK <hexbytes>` |
| `POKE` | addr bytes (≤32 B) | Write memory (protection table checked) | `ACK POKE <n>` |
| `STAT` | — | Mode, uptime, reboots, last fault | `ACK STAT <fields>` |
| `SAFE` | — | Enter safe mode | `ACK SAFE` |
| `NOOP` | — | Accepted, no action | `ACK NOOP` |
| `AUTH` | key (hex32) | *Undocumented.* Unlock engineering commands if key matches `eng_key` in config | `ACK AUTH` / `NAK E07` |
| `TRIM` | — | *Undocumented, privileged.* Manual reaction-wheel desaturation (needs `AUTH`) | `ACK TRIM` / `NAK E07` |
| `DUMP` | addr len (≤512) | *Undocumented, **ships disabled**.* Bulk read — 8 commands per image frame instead of 64 | `ACK DUMP <hexbytes>` / `NAK E08` |

The last two verbs are **not** in the recovered manual — they are an engineering back-channel the player discovers by reverse engineering the command dispatcher, and the natural seed for a security scenario: recover the `eng_key` from the binary to unlock privileged control, or (defensively) change the key an attacker would use. `NAK E07` is "unauthorized." The scheduler and dispatcher are table-driven, so adding further gated verbs is a content decision, not a rewrite.

Error replies: `NAK E01` bad CRC · `E02` unknown verb · `E03` unmapped address · `E04` protected region · `E05` bad length/args · `E06` busy · `E07` unauthorized · `E08` capability disabled. The ACK/NAK layer is deliberately dumb: it confirms *receipt and execution*, never mission effect (charter R1). Transmission delay and uplink budget are enforced by the game daemon, not the probe; the probe answers as fast as it can.

**A capability to be restored, not a convenience.** `DUMP` is present in the dispatcher but gated by `g_dump_enable`, which ships `0`. A player who discovers the verb gets `NAK E08` — *capability disabled*, not *unknown verb* — so the probe announces that a bulk downlink exists and is switched off. Early scenarios therefore pay the authentic 64-command image downlink, and a later objective becomes "restore the probe's bulk downlink," solved by patching one byte. Friction turns into content instead of tax.

Deliberate omission: there is no `CALL` verb. Executing injected code requires hooking the task table (or patching a call site) — keeping the hardest objective an act of understanding, not a built-in convenience. Adding `CALL` later is a one-line scenario-difficulty decision; the dispatcher is table-driven to make that trivial.

## 9. Downlink Telemetry Format

One frame per telemetry period (default 5 s, config block), emitted as a hex-encoded line prefixed `TLM ` on the UART. Binary layout:

| Field | Size | Notes |
|---|---|---|
| SYNC | 2 B | `0xEB90` |
| LEN | 1 B | Payload length |
| FRAME_CNT | 2 B | Wraps |
| UPTIME | 4 B | Seconds since boot — resets on watchdog recovery |
| MODE | 1 B | `0` BOOT, `1` NOMINAL, `2` SAFE |
| REBOOTS | 1 B | From NOINIT — survives recovery |
| LAST_FAULT | 1 B | Fault code of most recent reset |
| BUS_MV / LOAD_MW | 2+2 B | From PWR sensor; LOAD is the honest sum of sensor draw |
| Channels | TLV × n | One `{ID u8, LEN u8, VALUE}` per sensor that is powered **and** polled; absent otherwise |
| CAM | TLV | Channel `0x43`: capture metadata — frame id, target index, exposure, `HIST_MEAN`, `SAT_PCT`, `STARS` (present only after at least one capture) |
| COMMS | TLV | Channel `0x61` (4 B): antenna (`0` HGA / `1` LGA), channels dropped this frame, current payload budget (§6.4b) |
| HK | TLV | Channel `0x60` (8 B): auxiliary flight functions (§6.4) — `heater_on` u8, `shed_count` u8, `propellant_mg` u16, `momentum` s16, `rec_fill_pct` u8, `auth` u8. Absent in SAFE mode |
| AUX | TLV | Channel `0x5A`: undocumented in the player manual (charter R10) — content TBD with scenario (candidate: CRC of last accepted command, closing the feedback loop for attentive players) |
| CRC | 2 B | CRC-16/CCITT over frame after SYNC |

Channels are emitted in `tlm_priority[]` order and only while they fit the current antenna's payload budget (§6.4b); what does not fit is dropped whole and counted.

Design intent: the frame is decodable from the recovered manual plus observation; a disabled sensor *vanishes* rather than reading zero — the difference is the game's primary success signal and is trivially assertable by the daemon.

## 10. Watchdog & Fault Handling

The watchdog is a down-counter in the protected system block, decremented by the bootloader-owned SysTick handler — outside the patchable APP region, so it cannot be patched away (C2). The application's `wdg_pet` task reloads it through a ROM service call. Expiry → system reset via `AIRCR.SYSRESETREQ` with fault code `WDG` recorded; hard faults, bus faults, and usage faults likewise record codes and reset. Patching out `wdg_pet`, corrupting the scheduler, or jumping into garbage all funnel into the same observable recovery path. `MODE_SAFE` (entered by `fault_monitor` or the `SAFE` verb) drops telemetry to a minimal frame and de-powers non-essential sensors — scenario-usable both as a hazard and as a tool.

## 11. Build Artifacts & the Content Seam

Each build emits, for the scenario package and daemon (C6): `probe_rom.elf` (full symbols — **instructor/author side only**), `probe_rom.bin` (what QEMU boots), `probe_app.bin` (stripped application image — **the player's `probe.bin`**), `symbols.json` (machine-readable map of every address named in this spec), and `memmap.json` (regions + protection table). Objective assertions in scenario packages reference `symbols.json` names, not raw addresses, so firmware rebuilds don't silently break scenarios.

## 12. Running & Introspection

```
qemu-system-arm -M mps2-an386 -kernel probe_rom.elf \
    -nographic -serial mon:stdio -gdb tcp::3333
```

The serial console shows `TLM` lines immediately; commands are typed (or piped) on the same UART. The daemon — or a student, or you — attaches GDB to port 3333 and reads live state, e.g. `x/8wx 0x2001E000` to watch the magnetometer's registers move while the simulated sensor runs. That command, sixty seconds after handing over the container, is the "see register values as if the sensors were active" demo. Renode substitutes its monitor (`sysbus ReadDoubleWord ...`) with identical observable behavior.

## 13. Patch Surface vs. Difficulty Ramp

How the charter's four-step ramp (R9) maps onto this design — each objective has at least two honest solutions:

| Objective | Intended surfaces (non-exhaustive) |
|---|---|
| 1. Disable failing sensor | MAG `CTRL.POWER` bit; or its polling-table enable flag (partial: power still drawn) |
| 2. Change mission parameter | Telemetry period / comms tunable in the config block |
| 3. Patch code | `fault_monitor` comparison or branch (stop spurious safe-mode trips); NOP a call site |
| 4. Inject functionality | Routine into the code cave (`0x2001_D000`) + hook an empty task-table slot, detour a function's 8-byte entry pad, or take an inline patch point (§6.5) |
| Camera missions (reference-scenario extras or scenario #2) | Retarget: `TARGET` register or a catalog entry's `scene` — the returned picture changes. Fix exposure: `EXPOSURE_MS`/`GAIN`, verified by `SAT_PCT` falling and `STARS` rising in channel `0x43`. **Image processing: rewrite `cam_lut` to invert/threshold/posterize, or `cam_kernel` to blur/sharpen/edge-detect — verified in telemetry by `HIST_MEAN`, or visually by recovering the frame.** Image downlink: `PEEK`-dump the frame buffer under the uplink budget |
| Auxiliary-function missions (§6.4, future scenarios) | Thermal: heater setpoint/enable, verified by `heater_on` + `LOAD_MW`. Power: `power_budget_mw`/`shed_enable`/shed-priority table, verified by `shed_count` and a vanishing sensor channel. Attitude: `acs_*` params/enable + `TRIM`, verified by `momentum`/`propellant_mg`. Recorder: `rec_*` params, verified by `rec_fill_pct`. Security: recover `eng_key`, `AUTH`-unlock, or re-key it — verified by the `auth` flag |

## 14. Documentation Split (spec → player manual)

The *Recovered Mission Operations Manual* is this spec, redacted in-fiction ("pages lost"): players **get** the documented command protocol verbs (§8, `PING`/`PEEK`/`POKE`/`STAT`/`SAFE`/`NOOP` — not `AUTH`/`TRIM`), the telemetry format minus AUX and HK (§9), the coarse memory map (ROM / APP / data regions and the protection rules — not the internal layout), the sensor list with slot IDs, boot/watchdog behavior described operationally, and the camera's basic operating registers (`CCTRL`, `EXPOSURE_MS`, `GAIN`, the stats registers) — presented as a surviving excerpt of the imaging handbook. Players **do not get**: task-table location or format, config-block layout (including the **target catalog** and all §6.4 function parameters, and the **engineering key** — finding these *is* the mission), free-RAM region, frame-buffer address (discoverable via `FRAME_ADDR`), the physics module, the imaging pipeline internals (`cam_lut`, `cam_kernel`, `cam_filter`, the stored scenes), the `AUTH`/`TRIM` verbs, the AUX and HK channels, or any symbol file. Everything withheld is discoverable in the binary — that's the game. (The manual's Appendix C hints that undocumented channels exist; `0x60` and `0x5A` are exactly those.)

## 15. Open Questions for Sponsor Review

**Resolved since first issue** (recorded so the reasoning is not lost):

- **Reproducibility** — *closed, and not a preference.* Charter R15.1 restores progress by replaying the command log against a fresh probe. Clock- or entropy-derived behavior would make a replayed log diverge, so determinism is an architectural requirement: a fixed PRNG seed for sensor physics, and a replay-deterministic roll for the imaging easter egg.
- **Cortex-M4 vs M3** — *closed.* M4 on `mps2-an386` builds, boots and passes the full suite; the M3/LM3S path remains a documented fallback behind a build flag.
- **AUX channel content** — *closed.* CRC echo of the last accepted command: a quiet confirmation that rewards attentive frame decoders.
- **Bulk image downlink** — *closed.* `DUMP` ships **disabled** (§8): early missions pay the 64-command downlink, and restoring the capability becomes an objective.
- **`CALL` verb** — *closed: added, doubly gated.* It fills the gap in the difficulty ladder between "NOP out a branch" and "write Thumb assembly and hook the scheduler," and is safe there because `CALL` runs a routine *once* while a task hook makes it run *forever* — only the latter changes the probe's behavior. It requires `AUTH` **and** ships disabled behind `g_call_enable`, so an instructor enables it for an intro scenario and leaves it off when the canyon should stay.
- **Mission fiction vs. imaging targets** — *closed.* Targets moved outward rather than the mission moving inward: the scene set is now Pluto, Nix and Arrokoth, placing Sojourn in the Kuiper Belt, consistent with a signal delay measured in hours.
- **Uplink budget vs. imaging** — *closed (charter R4.2/R4.3).* The budget meters only state-changing uplinks; reads run on a separate allowance. A scenario can therefore hold a tight patch budget and a full image downlink at once.
- **Detector store readability** — *closed: left readable.* A player who finds `0x0002_4000` can dump the source imagery. Note the interaction with `DUMP`: once bulk downlink is unlocked that costs 18 commands rather than 144, so a scenario that unlocks `DUMP` also makes the easter egg cheaper to spoil. Accepted.
- **Scene resolution** — *closed: 96×96.* Real spacecraft photographs carry appreciably more at 96×96 (9216 bytes); a full downlink is 144 `PEEK`s, or 18 with `DUMP` enabled.
- **Housekeeping channel visibility** — *closed.* Channel `0x60` is **documented** in the player manual: it is the only view of heater, propellant, recorder and access state, and the §6.4 flight-function scenarios are unplayable without it. `AUX` (`0x5A`) remains the deliberately undocumented channel satisfying charter R10.2.

**Still open:**

1. **Telemetry cadence** (§9). 5 s remains a guess, and now couples to recorder drain rate and image-downlink pacing. A playtest answer, not a desk answer.
4. **Uplink budget vs. imaging** (charter R4.2). A budget tight enough to make patching feel precious can make a 64-command image downlink impossible. These must be tuned together, or imaging needs its own allowance — the `DUMP` gate is one lever.
5. **Is the detector store `PEEK`-readable?** Currently yes: a player who finds `0x0002_4000` can dump the source imagery at 64 bytes per command. Recommended to keep — it is expensive, and discovering an easter egg by reverse engineering is the point — but a scenario wanting the imagery strictly unreachable can exclude the range from `readable()`.
6. **Scene resolution** (§6.4a). 64×64 was sized for a synthetic star field; real spacecraft photographs would carry noticeably more detail at 96×96 or 128×128, at 2–4× the downlink cost.

---

*Version 0.7 — the firmware described here is built, boots under QEMU and passes an 81-check end-to-end suite. Remaining §15 items are content and tuning decisions, not blockers.*
