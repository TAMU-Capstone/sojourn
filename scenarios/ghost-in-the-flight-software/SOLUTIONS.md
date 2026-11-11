# Solutions: Ghost in the Flight Software (Instructor Only; Do Not Ship)

Each graded objective has two documented patch strategies (charter R9.2).
Strategy A is `solution.txt` and strategy B is `solution-alt.txt`. Both are
runnable with `firmware/tools/scenario_eval.py --script`, and both complete
every objective.

## `code-recorder` (code patch)

`task_recorder` (0x200022C4) has an 8-byte entry pad and a second 8-byte patch
point at 0x200022FA, where `r1` holds the summed generation and `r0` the drain rate.

| | Strategy A: stub the task | Strategy B: zero the generation term |
|---|---|---|
| Where | Entry pad, 0x200022C4 | Mid-body patch point, 0x200022FA |
| Code | `bx lr; nop; nop; nop` | `movs r1, #0` |
| Moves | `POKE 0x200022C4 704700BF00BF00BF`, then `POKE 0x20019326 0000` to drain the backlog by hand | `POKE 0x200022FA 0021` |
| Behaviour | Task returns immediately and the buffer freezes, so it must be zeroed manually | Task keeps running and always takes the drain branch, so the buffer empties itself at 64 B/s (~13 frames from full) |

Predicate: `sustained` 3 frames of `g_rec_fill == 0`, and `task_recorder`'s
whole body (124 bytes, not just the entry pad) changed.

## `injection-mag` (code injection)

Setup clears `poll_enable[MAG]`. Both strategies place a routine in the code
cave at 0x2001D000 that writes `poll_enable[0] = 1`. They differ in how the
scheduler is made to run it every cycle.

| | Strategy A: trampoline | Strategy B: scheduler hook slot |
|---|---|---|
| Cave | `ldr r0,=poll_enable; movs r1,#1; strb r1,[r0]; ldr r2,=task_acs+8\|1; bx r2` | `ldr r0,=poll_enable; movs r1,#1; strb r1,[r0]; bx lr` |
| Hook | Detour `task_acs`'s entry pad: `POKE 0x20002270 DFF800F001D00120` (`ldr.w pc,[pc]; .word cave\|1`) | Register in empty `task_table[12]`: `POKE 0x200190C4 01D00120640000000100000001000000` (handler = cave\|1, period 100, countdown 1, ENABLED) |
| Cave move | `POKE 0x2001D000 024801210170024A104700BF8091012079220020` | `POKE 0x2001D000 014801210170704780910120` |
| Risk | Must return past the pad, or ACS breaks | Handler must have the Thumb bit set. Write the cave first or the scheduler jumps into empty RAM. |

Predicate: `sustained` 5 frames of MAG present and `poll_enable[0] == 1`, the
cave changed, and *either* `task_acs`'s entry pad or a hook-slot handler
(`task_table+192` / `+208`) changed.

## Verified

Both scripts were run end to end in QEMU against the current `objectives.json`
(2026-11-11). In the B run, three PEEKs come first so the recorder fills to
4096 before the patch, and the trace shows it draining 320 B per frame to 0.

| Script | `code-recorder` | `injection-mag` | Writes |
|---|---|---|---|
| `solution.txt` | complete, frame 3 | complete, frame 8 | 4 |
| `solution-alt.txt` | complete, frame 18 | complete, frame 22 | 3 |
