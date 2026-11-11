# Solutions: The Last Transmission (Instructor Only; Do Not Ship)

Each graded objective has two documented patch strategies (charter R9.2).
Strategy A is `solution.txt` and strategy B is `solution-alt.txt`. Both are
runnable with `firmware/tools/scenario_eval.py --script`, and both complete
every objective.

## The squeeze

On the low-gain antenna, `comms_budget()` gives `rate_bps * tlm_period / (TICK_HZ * 8)`
= 64 * 500 / 800 = **40 bytes** per frame. The 13-byte header, COMMS (8) and HK (10)
leave 9 bytes, which is room for exactly one 6-byte science channel. The first one
in `tlm_priority` order that is being polled wins, which is MAG by default.

## `data-priority` (data patch)

| | Strategy A: reorder | Strategy B: cut the competition |
|---|---|---|
| Surface | `tlm_priority[10]` | `poll_enable[6]` |
| Move | `POKE 0x20019438 6160040001020305435A` | `POKE 0x20019180 00000000` |
| Idea | Move RAD (0x04) ahead of the other sensors | Stop polling MAG, IMU, THM, PWR. An unpolled channel has size 0 in the triage, so RAD is the first one that fits. |
| Cost | Leaves the other science channels in polling | Four instruments go dark until there is bandwidth again |

Predicate: `sustained` 3 frames of LGA, RAD present, and *either* table changed.
Both surfaces are data tables, so the objective is still a data patch (R9.1).

## `config-bandwidth` (configuration patch)

| | Strategy A: faster link | Strategy B: slower cadence |
|---|---|---|
| Field | `g_config.lga_rate_bps` 64 → 128 | `g_config.tlm_period` 500 → 1000 ticks |
| Moves | `POKE 0x20019164 8000` | `POKE 0x200190E4 E8030000`, `POKE 0x20019068 E8030000`, `POKE 0x20019181 01` |
| Result | 80 B/frame, frames every 5 s | 80 B/frame, frames every 10 s |

Strategy B notes:

- The scheduler copies `tlm_period` into `task_table[6].period` at boot, so
  changing the config alone raises the budget without slowing the cadence. That
  over-runs the link, which the model does not catch. The honest version also
  writes `task_table[6].period` at `task_table+0x64`.
- `task_table+0x60` is the *handler*, not the period. Writing 1000 there
  crashes the probe into a reboot. This is a good trap to discuss.
- If B was also used for `data-priority`, IMU has to be re-enabled
  (`poll_enable[1] = 1`) for the objective's IMU-present check.

Predicate: `sustained` 3 frames of LGA, RAD and IMU present, and *either*
`lga_rate_bps > 64` or `tlm_period > 500`.

## Verified

Both scripts were run end to end in QEMU against the current `objectives.json`
(2026-11-11):

| Script | `data-priority` | `config-bandwidth` | Writes |
|---|---|---|---|
| `solution.txt` | complete, frame 7 | complete, frame 9 | 2 |
| `solution-alt.txt` | complete, frame 6 | complete, frame 8 | 4 |
