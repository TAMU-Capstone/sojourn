# Solutions: Ghost in the Flight Software (Instructor Only; Do Not Ship)

Revision 2. Each graded objective has two documented patch strategies (charter
R9.2). Strategy A is `solution.txt` and strategy B is `solution-alt.txt`. Both
are runnable with `firmware/tools/scenario_eval.py --script`, both complete
every objective, and both are replayed by `conformance/run_conformance.py`.

## Setup: what the player is up against

| Write | Purpose |
|---|---|
| `hga_fail_after_s = 20` | The high-gain antenna jams and the link falls back to the low-gain omni. Only one science channel fits per frame, and MAG is first in priority, so whether MAG is alive is visible at a glance. |
| `rec_gen_per_sensor = 100`, `rec_buffer_max = 2048` | The recorder saturates within seconds. The smaller buffer drains in about 32 s if allowed to. |
| `poll_enable[MAG] = 0` | MAG starts silent. |
| **The ghost** at cave+0xF00, registered in `task_table[13]` (every 10 s) | Each run: if `poll_enable[MAG]` is set, add one to a u16 tally at cave+0xFF0, then clear the flag. |
| `settle_frames = 3` | The recorder is full before the player gets control. |

The ghost is what makes the injection objective gradeable. A one-off write
turns MAG on until the ghost's next run, then it's gone. Only code that keeps
running pushes the tally up cycle after cycle. Players who read `task_table`
can find the ghost in slot 13 and disassemble it.

## `code-recorder` (code patch)

`task_recorder` (0x200022C4) has an 8-byte entry pad and a second 8-byte patch
point at 0x200022FA, where `r1` holds the summed generation and `r0` the drain rate.

| | Strategy A: stub the task | Strategy B: zero the generation term |
|---|---|---|
| Where | Entry pad, 0x200022C4 | Mid-body patch point, 0x200022FA |
| Code | `bx lr; nop; nop; nop` | `movs r1, #0` |
| Moves | `POKE 0x200022C4 704700BF00BF00BF`, then `POKE 0x20019326 0000` to drain the backlog by hand | `POKE 0x200022FA 0021` |
| Behaviour | Task returns immediately and the buffer freezes, so it must be zeroed manually | Task keeps running and always takes the drain branch, so the buffer empties itself at 64 B/s (~7 frames) |

**Success**, `sustained` 3 frames, all of:
- `task_recorder`'s whole body (124 bytes) has changed;
- `g_rec_fill == 0`;
- the recorder config (`g_config` +112..119: enable, buffer max, generation, drain) is unchanged;
- `poll_enable[IMU..STR]` is unchanged;
- IMU..STR are all still powered (sensor `CTRL` bit 0).

The last three checks close the non-code shortcuts: disabling the recorder,
shrinking its buffer, raising its drain, or switching instruments off so they
generate nothing.

**Partials:** recorder config changed; instruments switched off or unpolled;
code patched but buffer not yet empty.

## `injection-mag` (code injection)

Both strategies place a routine in the code cave at 0x2001D000 that writes
`poll_enable[0] = 1`, and get the scheduler to run it every second. The ghost
then clears the flag every 10 s and the hook restores it within a second.

| | Strategy A: trampoline | Strategy B: scheduler hook slot |
|---|---|---|
| Cave | `ldr r0,=poll_enable; movs r1,#1; strb r1,[r0]; ldr r2,=task_acs+8\|1; bx r2` | `ldr r0,=poll_enable; movs r1,#1; strb r1,[r0]; bx lr` |
| Hook | Detour `task_acs`'s entry pad: `POKE 0x20002270 DFF800F001D00120` (`ldr.w pc,[pc]; .word cave\|1`) | Register in empty `task_table[12]`: `POKE 0x200190C4 01D00120640000000100000001000000` (handler = cave\|1, period 100, countdown 1, ENABLED) |
| Cave move | `POKE 0x2001D000 024801210170024A104700BF8091012079220020` | `POKE 0x2001D000 014801210170704780910120` |
| Risk | Must return past the pad, or ACS breaks | Handler must have the Thumb bit set. Write the cave first or the scheduler jumps into empty RAM. |

**Success**, all of:
- the cave's first 32 bytes changed;
- `task_acs`'s pad or `task_table[12].handler` changed;
- ghost tally ≥ 3;
- MAG present within the last 2 frames;
- no ground `POKE` to `poll_enable` or to the tally, ever.

MAG is checked with `within` rather than `sustained`: a frame sampled in the
second after a ghost run legitimately misses MAG, and that flicker is the hook
doing its job.

**Partials:**
- `poll_enable` hand-written. This is permanent: the objective can no longer be completed.
- The ghost slot disabled or overwritten.
- Code in the cave but no hook.
- Hook installed, waiting for cycles.

**Known gaps:**
- The `commanded` check matches the exact address, so a `POKE` that starts one
  byte early and spans `poll_enable[0]` is not caught. It would still need the
  tally to rise three times, i.e. three hand writes spaced across ghost runs.
- Writing a no-op into the cave and `task_acs` passes the "changed" checks, but
  without a working hook the tally does not rise.

## Grading tests

Run in QEMU with the reference evaluator on 2026-11-11. The fixtures marked ✓
are replayed by the conformance suite.

| Script | `code-recorder` | `injection-mag` | Writes |
|---|---|---|---|
| `solution.txt` ✓ | complete, frame 4 | complete, frame 10 | 4 |
| `solution-alt.txt` ✓ | complete, frame 9 | complete, frame 9 | 3 |
| Hand-poke `poll_enable` 4× after no-op hook edits ✓ (`ghost-hand-poke`) | complete | **active** | 8 |
| Disable ghost slot, then install a correct hook | complete | **active** | 5 |
| `rec_enable = 0` + no-op code edit + zero fill | **active** | locked | 3 |
| Power off IMU..STR + no-op code edit + zero fill | **active** | locked | 7 |
