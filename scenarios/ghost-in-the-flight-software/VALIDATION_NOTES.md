# Validation Notes (Developer Only; Do Not Ship as Player-Facing Documentation)

## Scenario: Ghost in the Flight Software

> **Superseded in part by revision 2.** The objective conditions, setup and test results below describe revision 1. For the current predicates, both solution strategies, the negative tests and the conformance fixtures, see `SOLUTIONS.md`.

This scenario has been tested using the Sojourn backend and QEMU firmware through a standalone headless testing harness. Both objectives have been successfully completed using the intended patch sequence. A negative test and an additional injected-hook recovery test were also performed.

## Scenario Overview

This is the advanced scenario from the original four-patch candidate, separated into its own independent mission.

The scenario requires the player to modify executable firmware code to stop a runaway recorder and install an injected routine that restores instrument polling.

The scenario includes two objectives:

1. **Halt the runaway recorder (`code-recorder`)** — Patch the executable recorder task to prevent additional recorder fill while preserving telemetry.
2. **Install autonomous instrument recovery (`injection-mag`)** — Inject code into free RAM, redirect an existing scheduled task through the injected routine, and restore magnetometer reporting.

The second objective requires completion of the first.

## Positive Runtime Testing

Both objectives were successfully completed in QEMU.

### Objective 1: Halt the Runaway Recorder

Patch applied:

```text
POKE 0x200022C4 704700BF00BF00BF
```

The firmware acknowledged the patch with `ACK POKE 8`.

The `code-recorder` objective completed successfully after the recorder task was modified and the recorder fill condition was satisfied for the required three consecutive frames.

### Objective 2: Install Autonomous Instrument Recovery

The following patches were applied:

```text
POKE 0x2001D000 024801210170024A104700BF8091012079220020
POKE 0x20002270 DFF800F001D00120
```

Both commands were acknowledged successfully with `ACK POKE 20` and `ACK POKE 8`, respectively.

The `injection-mag` objective completed successfully after the injected code and task detour were installed, magnetometer telemetry remained present, and `poll_enable` was observed as enabled for the required five consecutive frames.

Throughout the test, the firmware remained in NOMINAL mode with zero reboots, and telemetry CRC checks passed.

## Negative Testing

A separate test was performed to verify that manually enabling instrument polling without installing the injected code and task detour would not complete the second objective.

The recorder patch was applied, followed by:

```text
POKE 0x20019180 01
```

The first objective completed, but `injection-mag` remained active.

This confirmed that enabling `poll_enable` alone was insufficient to satisfy the second objective.

## Injected Hook Recovery Testing

An additional test was performed to investigate whether the injected hook continued operating after the second objective completed.

After installing the recorder patch, injected routine, and task detour, the polling flag was manually disabled using:

```text
POKE 0x20019180 00
```

The firmware acknowledged the write with `ACK POKE 1`.

Subsequent reads of the same address returned:

```text
ACK PEEK 01
ACK PEEK 01
```

These results are consistent with the injected routine restoring the polling flag after it was manually disabled.

The firmware remained in NOMINAL mode with zero reboots throughout this test.

This provides additional functional evidence that the injected routine executes after installation. However, the test did not directly observe the flag at zero between the acknowledged write and the subsequent reads, and it does not independently establish the exact execution frequency.

## Current Objective Validation

The current objectives use the following conditions:

**`code-recorder`:**
- Recorder task executable memory has changed.
- Recorder fill equals zero.
- Both conditions hold for three consecutive frames.

**`injection-mag`:**
- The scheduled ACS task entry has changed.
- The injection code cave has changed.
- MAG telemetry is present.
- `poll_enable` equals 1.
- All conditions hold for five consecutive frames.

The original conditions involving `g_desat_count > 3` and RAD telemetry were removed during testing because they did not reliably represent the intended successful behavior.

The current conditions have passed the intended positive test and the manual-polling negative test.

## Remaining Limitations

The scenario has been functionally tested using the intended solution, but full compliance with every formal requirement has not yet been established.

In particular:

- The objective predicates do not strictly prove repeated execution of the injected routine. They verify the code modifications and sustained resulting state.
- The additional recovery test supports recurring hook behavior but does not directly count executions.
- Alternative valid solutions have not been exhaustively tested.
- Official static validation and recorded replay conformance testing have not yet been confirmed.
- The player-facing recovered manual should be reviewed for completeness against the firmware documentation before release.

## Conclusion

Both objectives have been successfully completed through end-to-end QEMU testing. The scenario has also passed a basic negative test and an additional injection recovery test.

The intended patch sequence works, the firmware remains stable, and the current objective conditions correctly recognize the tested solution.

**Status: Functionally validated for the intended solution. Full specification compliance and final release packaging remain to be verified.**

This file is developer-only documentation and should not be included in the player-facing distribution.