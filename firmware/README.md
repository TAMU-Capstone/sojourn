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

## Verify

    make test    # 36 checks: framing, protocol, protection,
                 # objective-1 flow, camera, brick+recover

## Layout

    boot/boot.c        ROM: vectors, golden-image copy, SysTick+watchdog, faults
    app/main.c         scheduler + task table (two empty hook slots)
    app/sensors.c      sensor register block + SIM-tier physics
    app/camera.c       imaging subsystem: star fields, stats, frame buffer
    app/telemetry.c    downlink frames (TLV channels, CRC16)
    app/command.c      uplink interpreter: PING/PEEK/POKE/STAT/SAFE/NOOP
    app/config.c       mission config block + target catalog
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
