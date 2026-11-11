# Validation Notes (Developer Only; Do Not Ship as Player-Facing Documentation)

## Scenario: The Last Transmission

> **Superseded in part by revision 2.** The objective conditions, setup and test results below describe revision 1. For the current predicates, both solution strategies, the negative tests and the conformance fixtures, see `SOLUTIONS.md`.

This scenario has been tested using the Sojourn backend and QEMU firmware through a standalone headless testing harness. Both objectives have been successfully completed using the intended patch sequence. A negative test was also performed to verify that an incorrect telemetry priority modification would not satisfy the first objective.

## Scenario Overview

This is the intermediate scenario from the original four-patch candidate, separated into its own independent mission.

The scenario requires the player to modify telemetry priority settings and increase the low-gain antenna bandwidth to restore transmission of important instrument data after high-gain antenna degradation.

The scenario includes two objectives:

1. **Restore telemetry priority (`data-priority`)** — Modify the telemetry priority table so that important channels, including RAD, can be transmitted over the limited low-gain antenna connection.
2. **Increase low-gain bandwidth (`config-bandwidth`)** — Modify the low-gain antenna rate configuration to allow additional telemetry channels, including IMU, to be transmitted.

The second objective requires completion of the first.

## Positive Runtime Testing

Both objectives were successfully completed in QEMU.

### Objective 1: Restore Telemetry Priority

Patch applied:

```text
POKE 0x20019438 6160040001020305435A
```

The firmware acknowledged the patch with `ACK POKE 10`.

After the telemetry priority table was modified, RAD telemetry became available over the low-gain antenna connection.

The `data-priority` objective completed successfully after the telemetry priority table changed, the antenna was operating in LGA mode, and RAD telemetry remained present for the required three consecutive frames.

### Objective 2: Increase Low-Gain Bandwidth

Patch applied:

```text
POKE 0x20019164 8000
```

The firmware acknowledged the patch with `ACK POKE 2`.

This increased the configured low-gain antenna rate from 64 to 128 bits per second. The reported telemetry budget increased from 40 to 80 bytes, allowing both RAD and IMU telemetry to be transmitted.

The `config-bandwidth` objective completed successfully after the rate exceeded 64, the antenna remained in LGA mode, and both RAD and IMU telemetry were present for the required three consecutive frames.

Throughout the positive test, the firmware remained in NOMINAL mode with zero reboots, and telemetry CRC checks passed.

## Negative Testing

A separate test was performed to verify that changing the telemetry priority table without restoring the required RAD telemetry would not complete the first objective.

The following patch was applied:

```text
POKE 0x20019438 61600001020304055A43
```

The firmware acknowledged the patch with `ACK POKE 10`.

Although the telemetry priority table was modified, RAD telemetry remained absent from the low-gain antenna transmission.

The `data-priority` objective remained active, and `config-bandwidth` remained locked throughout the observation period.

This confirmed that modifying the priority table alone was insufficient to satisfy the first objective when the required RAD telemetry was not present.

## Current Objective Validation

The current objectives use the following conditions:

**`data-priority`:**
- The telemetry priority table has changed.
- The antenna is operating in LGA mode.
- RAD telemetry is present.
- All conditions hold for three consecutive frames.

**`config-bandwidth`:**
- The configured low-gain antenna rate is greater than 64.
- The antenna is operating in LGA mode.
- RAD telemetry is present.
- IMU telemetry is present.
- All conditions hold for three consecutive frames.

Both objectives have passed the intended positive test. The first objective has also passed a negative test using an incorrect telemetry priority modification.

## Remaining Limitations

The scenario has been functionally tested using the intended solution, but full compliance with every formal requirement has not yet been established.

In particular:

- Alternative valid solutions have not been exhaustively tested.
- Negative testing has focused on an incorrect telemetry priority modification; not every possible incorrect configuration has been tested.
- Official static validation and recorded replay conformance testing have not yet been confirmed for the current final package.
- The player-facing recovered manual should be reviewed for completeness against the firmware documentation before release.

## Conclusion

Both objectives have been successfully completed through end-to-end QEMU testing. The scenario has also passed a negative test confirming that an incorrect telemetry priority modification does not satisfy the first objective.

The intended patch sequence works, the required telemetry channels become available, and the firmware remains stable throughout testing.

**Status: Functionally validated for the intended solution. Full specification compliance and final release packaging remain to be verified.**

This file is developer-only documentation and should not be included in the player-facing distribution.