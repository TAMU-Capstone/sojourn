# Ghost in the Flight Software

The probe's high-gain antenna has jammed and the link has fallen back to the low-gain omni, so every byte of downlink counts. Two things have gone wrong aboard at the same time.

The data recorder is filling far faster than it can drain. And the magnetometer has gone quiet: its polling is switched off, and when it is switched back on, it doesn't stay on. Mission Control suspects that correcting configuration alone will not solve either problem.

1. Patch the recorder task's code so the archive buffer empties and stays empty, without losing any instrument's telemetry.
2. Install a recurring routine in flight software that keeps the magnetometer reporting, while normal scheduled execution carries on.

Use memory reads and downlink telemetry to investigate the running firmware. Writes are limited.
