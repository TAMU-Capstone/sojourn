# Sojourn — Reference Flight Firmware

The instructor-supplied golden image for the Sojourn reverse engineering
game platform. Implements the Firmware Design Specification: ROM
bootloader with golden-image recovery, ROM-owned watchdog, cooperative
scheduler, six simulated sensors, the imaging subsystem, downlink
telemetry, and the PEEK/POKE uplink command interpreter.

**This tree is instructor/capstone-team material.** Players receive only
`build/probe_app.bin` (as `probe.bin`), the published memory map, and the
Recovered Mission Operations Manual — never this source, never
`symbols.json`.

## Prerequisites

Builds and tests identically on Linux and macOS. `make check` verifies
your setup and prints the right install command for your OS.

Debian/Ubuntu:

    sudo apt install gcc-arm-none-eabi binutils-arm-none-eabi \
                     qemu-system-arm gdb-multiarch

macOS (Homebrew):

    brew install arm-none-eabi-gcc arm-none-eabi-binutils qemu

or ARM's official toolchain bundle (includes `arm-none-eabi-gdb`):

    brew install --cask gcc-arm-embedded
    # then add /Applications/ArmGNUToolchain/<ver>/arm-none-eabi/bin to PATH

Python 3.9+ is required on both (macOS ships it; on Linux it is
typically already present).

## Build & run

    make check      # verify toolchain (per-OS hints if anything is missing)
    make            # -> build/probe_rom.elf, probe_app.bin, symbols.json, memmap.json
    make run        # boot under QEMU; telemetry appears immediately (Ctrl-A X quits)
    make gdbserver  # same, halted, GDB stub on :3333
    make gdb        # attach the cross-gdb it finds (arm-none-eabi-gdb or gdb-multiarch)
    make tlm        # boot the probe and stream DECODED telemetry (see below)
    make run-tcp    # boot with the UART on tcp:5599 (one client at a time)
    make test       # 81-check end-to-end suite

Overridable: `make CROSS=... QEMU_BIN=... PYTHON=...` if your tools have
nonstandard names or live off PATH.

## Talk to the probe

Commands need a CRC-16/CCITT-FALSE checksum over the text *including the
trailing space* before `*`:

    python3 - <<'EOF'
    def crc16(d):
        c=0xFFFF
        for b in d:
            c^=b<<8
            for _ in range(8): c=((c<<1)^0x1021)&0xFFFF if c&0x8000 else (c<<1)&0xFFFF
        return c
    for cmd in ["PING","STAT","PEEK 0x2001E000 16","POKE 0x2001E000 00000000"]:
        print(f"{cmd} *{crc16((cmd+' ').encode()):04X}")
    EOF

Paste the printed lines into the `make run` console. `POKE 0x2001E000
00000000` powers down the magnetometer: watch the MAG channel vanish from
the next TLM frame and the load fall — that is objective 1 of the
reference scenario, solved by hand.

Watch the sensors live from a second terminal while `make gdbserver` runs:

    make gdb
    (gdb) x/8wx 0x2001E000        # magnetometer slot, updating live

## Ground-side telemetry decoder (`tools/tlm_decode.py`)

The reference receiver/decoder for the downlink format (spec §9). This
tool is **normative**: the capstone team's game daemon must decode
frames exactly the way it does, and any change to the telemetry format
lands here in the same commit as the firmware change. It validates every
frame's CRC, decodes all channels with engineering units, and reports
frame-to-frame **events** — the signals the objective checker will
ultimately be built on.

### Input sources (mutually exclusive; stdin is the default)

| Invocation | Behavior |
|---|---|
| `--spawn [ROM_ELF]` | Boot QEMU itself and decode the live downlink. Default ELF: `build/probe_rom.elf`. `make tlm` is this. |
| `--connect HOST:PORT` | Attach to a running probe's serial TCP port (retries for up to 15 s). Pair with `make run-tcp` (port 5599). QEMU accepts **one** client at a time. |
| `--file PATH` | Decode a captured session log (any text containing `TLM` lines). |
| *(stdin)* | Decode a piped stream, e.g. `cat capture.txt \| python3 tools/tlm_decode.py`. |

### Options

| Flag | Effect |
|---|---|
| `--json` | One JSON object per frame on stdout (see below) instead of human-readable output. |
| `--raw` | Also echo non-telemetry lines (boot banner, `ACK`/`NAK` replies) prefixed `>>`. |

Exit status: `0` if every `TLM` line decoded cleanly, `1` if any frame
was undecodable (details go to stderr, decoding continues). A frame
with a wrong checksum prints `*** BAD CRC ***` and is otherwise ignored.

### Reading the output

    [0001] up=    10s NOMINAL reboots=0 fault=-  bus=3.303V load=775mW
           MAG    58 nT | IMU  0.02 °/s | THM 21.2 °C | PWR 3303 mV | RAD 8 ct | STR q=0.9069 | AUX 0x96B3
         ! CAM capture #1: target=0 exp=250ms mean=4 sat=0% stars=9

Header line, one per frame:

| Field | Meaning |
|---|---|
| `[0001]` | Frame counter (16-bit, wraps). |
| `up=` | Probe uptime in seconds — resets to ~0 after a watchdog recovery. |
| `NOMINAL` | Mode: `BOOT`, `NOMINAL`, or `SAFE` (SAFE frames carry no channels). |
| `reboots=` | Lifetime reset count from NOINIT — survives recovery. |
| `fault=` | Cause of the most recent reset: `-` none, `WDG`, `HARD`, `BADIMG`. |
| `bus=` / `load=` | Bus voltage and total load. `load` is the honest sum of every powered device — patches show up here. |

Sensor line — **a channel that is absent was not transmitted** (sensor
unpowered or unpolled); absence is data, and the raw wire values map to
units as follows:

| Channel | Wire value (s32) | Displayed |
|---|---|---|
| `MAG` | field strength | raw, nT |
| `IMU` | rate × 100 | value/100, °/s |
| `THM` | deci-°C | value/10, °C |
| `PWR` | bus millivolts | raw, mV |
| `RAD` | cumulative counts | raw, ct |
| `STR` | quaternion-w × 10000 | value/10000 |
| `AUX` (0x5A) | u16 | CRC-16 of the last accepted uplink command, hex |
| `CAM` (0x43) | 6 × u16 | shown as a capture event (below), not on the sensor line |
| `HK` (0x60) | 8 bytes | auxiliary flight functions — own `HK` line: heater, propellant, momentum, recorder fill, shed count, auth |
| `COMMS` (0x61) | 6 bytes | downlink and antenna state — own `LINK` line: antenna, payload budget, channels dropped, dish deployment, status flags |

Event lines (`!`) are computed by comparing consecutive frames:

| Event | Trigger |
|---|---|
| `channel X LOST` / `ACQUIRED` | A sensor channel disappeared from / returned to the downlink — the primary success signal for power-down objectives. |
| `PROBE REBOOTED (n -> m, fault=...)` | Reboot counter changed; fault code says why. A brick + watchdog recovery shows as `fault=WDG`. |
| `mode A -> B` | Mode transition (e.g. entering `SAFE`). |
| `CAM capture #id: target= exp= mean= sat= stars=` | `frame_id` advanced: a completed capture with its statistics — `sat`/`stars` are the exposure-objective signals (overexposure: `sat` up, `stars` down). |
| `ANTENNA HGA -> LGA` | The probe fell back to the low-gain antenna; the payload budget collapses and channels start dropping. |
| `DOWNLINK SATURATED: n channels dropped` | The frame no longer fits the current antenna's budget. |
| `HIGH GAIN ANTENNA JAMMED at n% deployment` | The dish backed out of full deployment and stalled. Re-deploying will not clear it. |
| `HGA POINTING ERROR` / `HGA boresight reacquired` | The dish lost or regained its attitude reference — powering the star tracker off costs the downlink about six seconds later. |
| `HGA deployment n% -> m%` | The deployment drive moved. |
| `DOWNLINK LOST (no link)` | Nothing will be transmitted: transmitter off, budget below a bare header, or the selected antenna cannot reach Earth. |

### Worked example: losing and regaining the high gain

A dish that stalls at 40 % deployment, the fallback to the omni, and the
recovery once the jam flag is patched away — every line below came from
the decoder against a live probe:

    [0002] up=    15s NOMINAL reboots=0 fault=-      bus=3.301V load=1675mW
           MAG     89 nT
           LINK LGA | budget=40B | dropped=6 | hga_deploy=40% | LINK,HGA_JAM,ON_LGA
         ! channel IMU LOST
         ! channel STR LOST
         ! ANTENNA HGA -> LGA (budget 100 -> 40 bytes)
         ! DOWNLINK SATURATED: 6 channels dropped
         ! HIGH GAIN ANTENNA JAMMED at 40% deployment

    [0007] up=    40s NOMINAL reboots=0 fault=-      bus=3.303V load=1855mW
           MAG    249 nT | IMU   0.14 °/s | THM  26.3 °C | PWR  3303 mV | ...
           LINK HGA | budget=100B | dropped=0 | hga_deploy=100% | LINK,HGA_DEPLOYED
         ! ANTENNA LGA -> HGA (budget 40 -> 100 bytes)
         ! dropped channels 6 -> 0

Three things are worth noticing. Only `MAG` survives the squeeze — the
40-byte budget holds the 13-byte header, the 8-byte `COMMS` channel, the
10-byte `HK` channel and exactly one 6-byte sensor, and `tlm_priority[]`
decides which. The bus load falls from 1855 mW to 1675 mW on the omni,
because the dish is no longer being steered. And the budget figures are
not constants: they are the link rate spread over one 5 s telemetry
period, so `tlm_period` is itself a way to buy bandwidth back.

### JSON mode

`--json` emits one object per frame — the shape the game daemon should
produce internally. Events are included, so a first-pass objective
checker can be a `jq` filter:

    {"crc_ok": true, "frame": 2, "uptime_s": 15, "mode": "NOMINAL",
     "reboots": 0, "last_fault": "-", "bus_mv": 3300, "load_mw": 595,
     "channels": {"IMU": 11, "THM": 212, "PWR": 3300, "RAD": 12,
                  "STR": 9075, "AUX": "0xD21D"},
     "events": ["channel MAG LOST"]}

Notes: sensor channel values are the **raw wire values** (no unit
scaling); `CAM` is a nested object (`frame_id`, `target`, `exposure_ms`,
`hist_mean`, `sat_pct`, `stars`); unknown channels appear as
`"0xNN": "<hex>"`. Example — watch for objective 1 completing:

    make run-tcp &
    python3 tools/tlm_decode.py --connect 127.0.0.1:5599 --json \
      | jq -c 'select(.events | index("channel MAG LOST"))'

### Typical sessions

    make tlm                       # one command: boot + live decoded stream
    make run-tcp                   # terminal 1: probe with UART on :5599
    python3 tools/tlm_decode.py --connect 127.0.0.1:5599 --raw   # terminal 2

To both send commands and decode, capture the single TCP session with
your client (or `nc`) and decode the log afterwards — or run `make tlm`
read-only alongside a scripted uplink session against `run-tcp`
(remember: one TCP client at a time).

## Verify

    make test    # 99 checks: framing, protocol, protection, objective-1
                 # flow, camera + imaging pipeline, flight functions,
                 # antennas + bandwidth triage, trampoline patching,
                 # brick + watchdog recovery

## Scenario tooling (`tools/scenario_*.py`)

These two belong to the *Scenario Package Format* specification rather than to
the firmware, but they live here because they need the build's `symbols.json`
and a probe to talk to.

`scenario_validate.py` checks a package statically — schema, symbol and field
resolution, memory-map bounds, dependency cycles, purity. It never starts a
probe, so it is fast enough for CI and for every save:

    python3 tools/scenario_validate.py ../scenarios/*        # PASS / FAIL
    python3 tools/scenario_validate.py --strict ../scenarios/comms-triage

`scenario_eval.py` is the **reference evaluator**: it boots a real probe,
applies a command log or a plain-text move list, evaluates the objectives
frame by frame, and reports which completed. It exists to prove the assertion
vocabulary is sufficient and to generate conformance fixtures — it is an
oracle, not a starting point for the game daemon.

    # play a scenario from a move list and record the log
    python3 tools/scenario_eval.py --scenario ../scenarios/comms-triage \
        --script ../scenarios/comms-triage/solution.txt \
        --record run.jsonl --out state.json --verbose

    # replay an existing log (the conformance entry point, format spec §10)
    python3 tools/scenario_eval.py conform \
        --scenario ../scenarios/comms-triage --replay run.jsonl --out state.json

`--verbose` prints objective transitions as they happen:

    scenario sojourn.comms.triage rev 1
      frame   5  diagnose -> complete
      frame   6  attempt-redeploy -> complete
      frame   8  restore-radiation -> complete
      frame   8  keep-budget -> complete

The whole acceptance gate — reference packages accepted, nine seeded defects
rejected, three replay fixtures agreeing — runs from the repository root:

    python3 conformance/run_conformance.py --reference     # 14 checks

Note that `symbols.json` is authoring material. It resolves the symbol names
scenarios reference, and it must never ship in a player image (charter R19).

## Layout

    boot/boot.c        ROM: vectors, golden-image copy, SysTick+watchdog, faults
    app/main.c         scheduler + task table (two empty hook slots)
    app/sensors.c      sensor register block + SIM-tier physics
    app/camera.c       imaging subsystem: star fields, stats, frame buffer
    app/telemetry.c    downlink frames (TLV channels, CRC16)
    app/command.c      uplink interpreter: PING/PEEK/POKE/STAT/SAFE/NOOP (+ undocumented AUTH/TRIM)
    app/flight.c       auxiliary flight functions: heater, power-shed, attitude, recorder
    app/comms.c        high/low gain antennas: deployment, pointing, link budget, channel priority
    app/imaging.c      image pipeline: transfer LUT, convolution kernel, filters
    app/scenes.c       GENERATED detector image store -> ROM, not the app image
    assets/            NASA source imagery for the scenes (+ credits)
    app/config.c       mission config block + target catalog + function tunables
    ld/                boot.ld (ROM), app.ld (execute-in-place at 0x20001000)
    tools/             image fixup, symbols generator, telemetry decoder,
                       image recovery (PNG), scene generator, e2e test,
                       scenario validator + reference evaluator
    include/probe.h    the memory-map contract (matches memmap.json)

## Camera images and the processing pipeline

Each catalog target selects one of five stored 96×96 grayscale scenes: a
survey star field, **Pluto**, **Nix** and **Arrokoth** (New Horizons), and
a hidden fifth — all photographs being NASA public-domain imagery kept in
`assets/`. The
camera reads the scene, runs it through a pipeline, and writes the result
into the frame buffer — which is what the ground downlinks. Pixels never
ride in telemetry, only capture statistics.

**The source images are not in the player's binary.** They live in a
*detector image store* in ROM at `0x00024000`, outside the golden
application image, reached via `SCENE_AT(i)`. `probe_app.bin` — the
player's `probe.bin` — contains no pixels, only the code that reads an
address. (Moving them cut it from 21,532 to 5,191 bytes.) A player can
still recover the source, but only by finding the address and
`PEEK`-dumping ROM, 64 commands per scene, against the uplink budget.

**Easter egg.** Scene 4 is referenced by no catalog entry, so it cannot
be commanded — but roughly 1 capture in 100 returns it anyway: a Cassini
image of Mimas, the moon whose Herschel crater makes it look like a
certain battle station. The roll advances from a fixed seed, not the clock, so a
replayed command log reproduces it exactly. `g_cam_egg_pct` sets the
rate (0 disables, 100 forces).

Every pipeline stage is a patch surface, easiest first:

| Stage | Surface | Ships as |
|---|---|---|
| Convolution | `cam_kernel[9]`, `cam_kdiv` | identity |
| Exposure/gain | `EXPOSURE_MS`, `GAIN` | 250 ms, ×16 |
| Transfer curve | `cam_lut[256]` | identity ramp |
| Stage select | `cam_filter` (config) | `FILT_LUT` |
| The loop | `image_process()` | entry pad + patch point |

The LUT stage is live but invisible as built, so **inverting the
downlinked image is a pure data patch** — 8 uplinks rewriting 256 bytes.
It is verifiable from telemetry alone (dark sky becomes bright, so
`HIST_MEAN` jumps) as well as visually.

Recover an actual picture — this drives the real downlink, 64 bytes per
`PEEK`, and writes a PNG with a stdlib-only encoder (no PIL):

    python3 tools/img_recover.py -o frame.png          # as built
    python3 tools/img_recover.py --invert              # inverting LUT
    python3 tools/img_recover.py --threshold 96
    python3 tools/img_recover.py --filter blur|sharpen|edge
    python3 tools/img_recover.py --target 2            # different scene
    python3 tools/img_recover.py --egg                 # force the easter egg

Everything the tool does is an ordinary uplink a player could type by
hand. Regenerate the scenes with `python3 tools/gen_scenes.py`.

## Patching space (trampolines)

The firmware pre-plants space so a patch that doesn't fit in place can
detour out and come back — the situation real missions hit, without the
hazard of relocating PC-relative instructions:

- **Entry pad** — every scheduled task begins with 8 bytes of NOPs
  (`PATCH_ENTRY`, i.e. `-fpatchable-function-entry`), ahead of its
  compiler prologue. Overwrite them with a jump; resume at `<func>+8`
  and the original body runs untouched.
- **Inline patch points** — 8-byte NOP sleds sit immediately before key
  decisions (thermostat, power budget, desaturation, recorder balance,
  safe-mode trip) via `PATCH_POINT()`.
- **Code cave** — 4 KiB of free RAM at `0x2001D000`, 32 × 128 B slots,
  where the injected instructions live.

The 8-byte absolute jump needs no offset math (Thumb bit set in the
target word):

    DF F8 00 F0     LDR.W PC, [PC, #0]
    <target|1>      .word

`make test` installs a real hook this way against `task_acs` and proves
both halves: the hook runs (a sentinel appears in telemetry) and control
returns into the original function (momentum keeps advancing). See spec
§6.5 for the worked example and the difficulty ladder.

## Design invariants (do not break these)

- The watchdog and vector table live in ROM; `VTOR` never points into RAM.
- Every reset re-copies the golden image; recovery is the only boot path.
- `POKE` protection comes from the ROM protection table, not app data.
- A sensor's telemetry channel requires power **and** polling — two
  independently patchable surfaces per objective.
- The app image carries no initialized `.data` (enforced by app.ld).
