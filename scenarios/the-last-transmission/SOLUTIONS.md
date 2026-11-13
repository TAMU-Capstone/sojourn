# Solutions: The Last Transmission (Instructor Only; Do Not Ship)

Revision 3. Each graded objective has two documented patch strategies (charter
R9.2). Strategy A is `solution.txt` and strategy B is `solution-alt.txt`. Both
are runnable with `firmware/tools/scenario_eval.py --script`, both complete
every objective, and both are replayed by `conformance/run_conformance.py`.

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

**Success**, `sustained` 3 frames: on LGA, RAD present, *either* table changed,
and the downlink still squeezed (`COMMS.budget` ≤ 40). The budget check is what
keeps this a data-patch objective (R9.1): without it, widening the link first
lets RAD in and any edit to either table completes the objective. It reads the
budget the probe reports rather than a config field, so it catches widening by
`lga_rate_bps` or `tlm_period` alike.

**Partials:**
- A table was changed but RAD is still squeezed out (the byte-count hint).
- The link has been widened (budget > 40): that is the next objective's fix; put
  it back and decide what goes first while it is tight.

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
  crashes the probe into a reboot, which now fails the objective. This is a
  good trap to discuss.
- If B was also used for `data-priority`, IMU has to be re-enabled
  (`poll_enable[1] = 1`) for the objective's IMU-present check.

**Success**, `sustained` 3 frames: on LGA, RAD and IMU present, and *either*
`lga_rate_bps > 64` or `tlm_period > 500`.

**Partials:**
- Budget raised but IMU absent ("is it actually being polled?").
- Budget raised but RAD dropped out again.

## Both objectives

- **Fail** if the probe enters SAFE mode or reboots. A reboot wipes the
  scenario's setup, so the run cannot be recovered.
- **Write budget** is 12. Strategy A uses 2 writes and strategy B uses 4.

## Grading tests

Run in QEMU with the reference evaluator on 2026-11-11. The fixtures marked ✓
are replayed by the conformance suite.

| Script | `data-priority` | `config-bandwidth` | Writes |
|---|---|---|---|
| `solution.txt` ✓ | complete, frame 7 | complete, frame 12 | 2 |
| `solution-alt.txt` ✓ | complete, frame 7 | complete, frame 14 | 4 |
| Raise `lga_rate_bps` only (skip the data patch) | **active**, with the "next objective's fix" partial | locked | 1 |
| Raise `lga_rate_bps`, then swap CAM/AUX in `tlm_priority` (rev. 3) | **active** | locked | 2 |

Both solution scripts wait (free `NOOP`s) for `data-priority` to complete before
widening the link. The reference evaluator applies one move per frame, and
widening before the squeezed objective has held for 3 frames on LGA now keeps it
active, which is the point of the revision-3 budget check. A player who widens
early gets the partial telling them to put the link back; `config-bandwidth` is
not shown to them until `data-priority` completes, so the briefing order already
steers them the right way.
