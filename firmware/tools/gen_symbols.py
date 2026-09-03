#!/usr/bin/env python3
"""gen_symbols.py — emit symbols.json + memmap.json (spec §11, C6).

symbols.json: instructor/scenario-author side only — never ships to
players.  Scenario assertions reference these names, not raw addresses.
"""
import json
import re
import subprocess
import sys

KEY_SYMBOLS = [
    # app
    "app_main", "task_table", "g_config", "g_mode", "poll_enable",
    "tlm_stage", "tlm_valid", "g_load_mw", "g_last_cmd_crc",
    "task_cmd", "task_physics", "task_sensor_poll", "task_wdg_pet",
    "task_fault_monitor", "task_camera", "task_telemetry",
    "enter_safe", "cmd_poll_rx",
    # auxiliary flight functions (flight.c)
    "flight_init", "task_heater", "task_power_mgr", "task_acs", "task_recorder",
    "g_heater_on", "g_heater_mw", "g_shed_count", "g_propellant_mg",
    "g_momentum", "g_desat_count", "g_rec_fill", "g_auth",
    # imaging pipeline (imaging.c / scenes.c)
    "image_process", "imaging_init", "cam_lut", "cam_kernel",
    "scene_store", "scene_for_target", "g_cam_egg_pct", "g_dump_enable", "g_call_enable",
    # comms / antennas / downlink bandwidth (comms.c)
    "task_comms", "comms_budget", "tlm_priority", "g_antenna",
    "g_hga_ok", "g_tlm_dropped", "g_comms_mw",
    # boot
    "rom_services", "rom_prot", "vectors",
]

MEMMAP = [
    {"name": "ROM_VECTORS",   "lo": 0x00000000, "hi": 0x00000400, "poke": "refused"},
    {"name": "ROM_BOOT",      "lo": 0x00000400, "hi": 0x00004000, "poke": "refused"},
    {"name": "ROM_GOLDEN",    "lo": 0x00004000, "hi": 0x00040000, "poke": "refused"},
    {"name": "NOINIT",        "lo": 0x20000000, "hi": 0x20000100, "poke": "refused"},
    {"name": "SYSBLK",        "lo": 0x20000100, "hi": 0x20001000, "poke": "refused"},
    {"name": "APP",           "lo": 0x20001000, "hi": 0x20019000, "poke": "writable"},
    {"name": "APP_DATA",      "lo": 0x20019000, "hi": 0x2001D000, "poke": "writable"},
    {"name": "FREE_RAM",      "lo": 0x2001D000, "hi": 0x2001E000, "poke": "writable"},
    {"name": "SENSOR_BLOCK",  "lo": 0x2001E000, "hi": 0x2001E100, "poke": "writable"},
    {"name": "CAM_REGS",      "lo": 0x2001E100, "hi": 0x2001E200, "poke": "writable"},
    {"name": "COMMS_REGS",    "lo": 0x2001E200, "hi": 0x2001F000, "poke": "writable"},
    {"name": "STACKS",        "lo": 0x2001F000, "hi": 0x20020000, "poke": "writable"},
    {"name": "CAM_FRAMEBUF",  "lo": 0x20020000, "hi": 0x20022400, "poke": "writable"},
]

def nm(elf: str) -> dict:
    out = subprocess.check_output(["arm-none-eabi-nm", elf], text=True)
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            addr, _kind, name = parts
            syms[name] = int(addr, 16)
    return syms

# Structures whose field offsets scenario authors need. Read from the DWARF of
# the actual target build rather than recomputed on the host, so the numbers
# are the ones the probe really uses. Scenario packages address these fields as
# {"sym": "g_config", "field": "hga_fail_after_s"} instead of hand-computed
# arithmetic -- see the Scenario Package Format spec, section 6.3.
STRUCT_FIELDS = {"config_t": "g_config"}


def struct_offsets(elf: str, typedef_name: str) -> dict:
    """Field name -> byte offset for a typedef'd struct, read from DWARF.

    The config block is `typedef struct { ... } config_t;` — an anonymous
    structure — so the name lives on the typedef and the members live on the
    structure DIE it points at. Resolve the typedef first, then walk that
    DIE's children.
    """
    try:
        raw = subprocess.check_output(
            ["arm-none-eabi-objdump", "--dwarf=info", elf],
            text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return {}

    lines = raw.splitlines()
    tag_re = re.compile(
        r"^\s*<(\d+)><([0-9a-f]+)>: Abbrev Number: \d+ \(DW_TAG_(\w+)\)")

    # Index every DIE: its line number, nesting level and DIE offset.
    dies = []
    for i, line in enumerate(lines):
        m = tag_re.match(line)
        if m:
            dies.append((i, int(m.group(1)), int(m.group(2), 16), m.group(3)))

    def attr(die_idx, key):
        start = dies[die_idx][0]
        end = dies[die_idx + 1][0] if die_idx + 1 < len(dies) else len(lines)
        for j in range(start + 1, end):
            if key in lines[j]:
                return lines[j].split(":")[-1].strip()
        return None

    # Find the typedef and follow its DW_AT_type to the structure's DIE offset.
    target = None
    for k, (_, _, _, tag) in enumerate(dies):
        if tag == "typedef" and attr(k, "DW_AT_name") == typedef_name:
            ref = attr(k, "DW_AT_type")
            if ref:
                target = int(ref.strip("<>"), 16)
                break
    if target is None:
        return {}

    # Collect the members that are direct children of that structure.
    fields = {}
    for k, (_, lvl, off, tag) in enumerate(dies):
        if off != target or tag != "structure_type":
            continue
        for j in range(k + 1, len(dies)):
            _, mlvl, _, mtag = dies[j]
            if mlvl <= lvl:
                break
            if mlvl == lvl + 1 and mtag == "member":
                name = attr(j, "DW_AT_name")
                loc = attr(j, "DW_AT_data_member_location")
                if name and loc is not None:
                    fields.setdefault(name, int(loc))
        if fields:
            break
    return fields


def main(app_elf: str, rom_elf: str, out_dir: str) -> None:
    syms = nm(rom_elf) | nm(app_elf)   # app wins on duplicates
    picked = {k: f"0x{syms[k]:08X}" for k in KEY_SYMBOLS if k in syms}
    missing = [k for k in KEY_SYMBOLS if k not in syms]
    if missing:
        print(f"warning: missing symbols: {missing}", file=sys.stderr)

    structs = {}
    for struct_name, sym in STRUCT_FIELDS.items():
        off = struct_offsets(app_elf, struct_name)
        if off:
            structs[sym] = off
        else:
            print(f"warning: no DWARF offsets for struct {struct_name}",
                  file=sys.stderr)

    with open(f"{out_dir}/symbols.json", "w") as f:
        json.dump({"format": 1, "symbols": picked, "fields": structs}, f, indent=2)
    with open(f"{out_dir}/memmap.json", "w") as f:
        json.dump({"format": 1, "regions": [
            {**r, "lo": f"0x{r['lo']:08X}", "hi": f"0x{r['hi']:08X}"} for r in MEMMAP
        ]}, f, indent=2)
    nf = sum(len(v) for v in structs.values())
    print(f"{out_dir}/symbols.json: {len(picked)} symbols, {nf} struct fields; "
          f"memmap.json: {len(MEMMAP)} regions")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
