#!/usr/bin/env python3
"""gen_symbols.py — emit symbols.json + memmap.json (spec §11, C6).

symbols.json: instructor/scenario-author side only — never ships to
players.  Scenario assertions reference these names, not raw addresses.
"""
import json
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
    "scene_data", "scene_for_target",
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
    {"name": "CAM_REGS",      "lo": 0x2001E100, "hi": 0x2001F000, "poke": "writable"},
    {"name": "STACKS",        "lo": 0x2001F000, "hi": 0x20020000, "poke": "writable"},
    {"name": "CAM_FRAMEBUF",  "lo": 0x20020000, "hi": 0x20021000, "poke": "writable"},
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

def main(app_elf: str, rom_elf: str, out_dir: str) -> None:
    syms = nm(rom_elf) | nm(app_elf)   # app wins on duplicates
    picked = {k: f"0x{syms[k]:08X}" for k in KEY_SYMBOLS if k in syms}
    missing = [k for k in KEY_SYMBOLS if k not in syms]
    if missing:
        print(f"warning: missing symbols: {missing}", file=sys.stderr)
    with open(f"{out_dir}/symbols.json", "w") as f:
        json.dump({"format": 1, "symbols": picked}, f, indent=2)
    with open(f"{out_dir}/memmap.json", "w") as f:
        json.dump({"format": 1, "regions": [
            {**r, "lo": f"0x{r['lo']:08X}", "hi": f"0x{r['hi']:08X}"} for r in MEMMAP
        ]}, f, indent=2)
    print(f"{out_dir}/symbols.json: {len(picked)} symbols; memmap.json: {len(MEMMAP)} regions")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
