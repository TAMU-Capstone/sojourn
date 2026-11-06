# Ghost in the Flight Software

The probe's recorder task is consuming resources, and magnetometer reports have disappeared. Mission Control suspects that repairing configuration alone will not solve these problems.

1. Patch the running recorder task to halt additional archive fill without losing telemetry.
2. Install a recurring flight-software hook that restores magnetometer polling while preserving normal scheduled execution.

Use memory reads and downlink telemetry to investigate the running firmware. Writes are limited, and the injected hook must continue to operate.
