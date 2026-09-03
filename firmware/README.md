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
    make test       # 36-check end-to-end suite

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
| `HK` (0x60) | 8 bytes | auxiliary flight functions — shown on its own `HK` line: heater, propellant, momentum, recorder fill, shed count, auth |

Event lines (`!`) are computed by comparing consecutive frames:

| Event | Trigger |
|---|---|
| `channel X LOST` / `ACQUIRED` | A sensor channel disappeared from / returned to the downlink — the primary success signal for power-down objectives. |
| `PROBE REBOOTED (n -> m, fault=...)` | Reboot counter changed; fault code says why. A brick + watchdog recovery shows as `fault=WDG`. |
| `mode A -> B` | Mode transition (e.g. entering `SAFE`). |
| `CAM capture #id: target= exp= mean= sat= stars=` | `frame_id` advanced: a completed capture with its statistics — `sat`/`stars` are the exposure-objective signals (overexposure: `sat` up, `stars` down). |

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

    make test    # 36 checks: framing, protocol, protection,
                 # objective-1 flow, camera, brick+recover

## Layout

    boot/boot.c        ROM: vectors, golden-image copy, SysTick+watchdog, faults
    app/main.c         scheduler + task table (two empty hook slots)
    app/sensors.c      sensor register block + SIM-tier physics
    app/camera.c       imaging subsystem: star fields, stats, frame buffer
    app/telemetry.c    downlink frames (TLV channels, CRC16)
    app/command.c      uplink interpreter: PING/PEEK/POKE/STAT/SAFE/NOOP (+ undocumented AUTH/TRIM)
    app/flight.c       auxiliary flight functions: heater, power-shed, attitude, recorder
    app/config.c       mission config block + target catalog + function tunables
    ld/                boot.ld (ROM), app.ld (execute-in-place at 0x20001000)
    tools/             image fixup, symbols.json generator, e2e test
    include/probe.h    the memory-map contract (matches memmap.json)

## Design invariants (do not break these)

- The watchdog and vector table live in ROM; `VTOR` never points into RAM.
- Every reset re-copies the golden image; recovery is the only boot path.
- `POKE` protection comes from the ROM protection table, not app data.
- A sensor's telemetry channel requires power **and** polling — two
  independently patchable surfaces per objective.
- The app image carries no initialized `.data` (enforced by app.ld).
