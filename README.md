# Sojourn

A reverse engineering game platform — Software & Cybersecurity Capstone,
supervised by Trevor Bakker.

A deep-space probe is failing and its source code has been lost. Players
reverse engineer the ARM flight binary in Ghidra and keep the mission
alive by patching the running probe over a narrow uplink — the way NASA
patched Voyager 1 in flight. The capstone team builds the platform around
it: emulated probe, ground-station console, scenario engine, and one
polished reference mission.

## Contents

- `docs/` — project charter & requirements (SHALL-form, verifiable),
  firmware design specification, capstone pitch deck
- `firmware/` — the instructor-supplied reference flight firmware
  (golden image): ARM Cortex-M4, boots under QEMU, simulated sensors +
  camera, telemetry, PEEK/POKE command interpreter, watchdog recovery.
  `make check && make test` — builds and tests on Linux and macOS.

## Documentation

Sources are the markdown files in `docs/`; the `.docx`, `.pdf` and
`requirements.md` beside them are generated. Edit the markdown, then:

    cd docs
    make deps     # once - installs the one npm package the Word exports need
    make          # rebuilds everything your machine can build
    make check    # requirement identifiers resolve; reports what is installed

`make` degrades rather than failing: without node it skips the Word exports,
without a Chromium or Chrome it still writes `manual.html` and skips the PDF.
`requirements.md` is generated from `charter.md` and must never be hand-edited.

## Quick start

    cd firmware
    make check   # verify toolchain (prints per-OS install hints)
    make run     # boot the probe; telemetry streams immediately
    make test    # 36-check end-to-end suite

Player-facing material (the stripped `probe.bin`, memory map, and the
Recovered Mission Operations Manual) is derived from this tree — the
tree itself is instructor/team material and is not handed to players.
