# Grader Hygiene (conformance fixture)

This is not a playable scenario and is never shipped to players. It is a
trap for one specific daemon defect.

Telemetry channel `0x5A` reports the CRC-16 of the **last accepted uplink
command**. The command log for this fixture ends with a single `PING`, whose
CRC is `0x2F40`, and nothing the player does afterwards touches the link. So
in a correct system the AUX channel reads `0x2F40` in every subsequent frame,
forever.

The objective below asserts that, *and* forces a memory read in the same
evaluation pass. A daemon that satisfies the memory read by sending `PEEK`
over the command channel overwrites `g_last_cmd_crc` with the CRC of its own
read, AUX stops reading `0x2F40`, and the objective never completes.

A daemon that reads out of band per the Introspection API passes without
noticing the trap exists.
