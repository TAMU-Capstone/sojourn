# Recovered Mission Operations Manual — DRAFT, INCOMPLETE

**Not yet compliant with R10.1:** this is a mission-specific excerpt, not a complete field-by-field decoder manual. The full sponsor-provided manual is required before player release.

Downlink frames use sync `EB 90` and CRC-16/CCITT-FALSE (poly `0x1021`, init `0xFFFF`). The known science channel identifiers are MAG `0x00`, IMU `0x01`, THM `0x02`, PWR `0x03`, RAD `0x04`, STR `0x05`, and CAM `0x43`. Housekeeping is `0x60` and communications is `0x61`. An additional channel may appear in the downlink; this excerpt does not document it.

MAG reports magnetic field in nT; IMU reports rate in hundredths of degrees per second; THM reports deci-degrees Celsius; PWR reports millivolts; RAD reports cumulative counts. The communications channel includes antenna selection, deployment percentage, and dropped-channel count. This document does **not** yet give the byte-level offsets necessary to decode every field; do not treat it as the final manual.
