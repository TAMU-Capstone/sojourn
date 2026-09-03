# First Contact

Sojourn has been quiet for eleven years. Yesterday the deep-space network
picked her up again, still transmitting, still on the same telemetry format
the mission used in 2015 — and nobody who wrote the flight software is still
with the agency.

You have the recovered operations manual. It is incomplete. You do not have
the source code; that was lost with the ground segment during the
consolidation. What you do have is a probe that answers when you talk to it.

Before anything ambitious, three things need establishing.

**One.** That the link works at all, and that the probe is listening.

**Two.** That you can read the downlink. The frames are hexadecimal because
that is what the transmitter sends; decoding them is your problem, and it is
the skill everything else in this program rests on.

**Three.** That you can change the probe's behavior and *see* that you
changed it. Turning a sensor off is the smallest such change: a science
channel that was in every frame stops appearing. Not zeroed — gone. A
disabled instrument does not report zero, it reports nothing, and knowing the
difference between those two is the beginning of reading this spacecraft
honestly.

The magnetometer is the safest instrument to practice on. It is not needed
for attitude, it is not needed for power, and nothing else depends on it.

Take your time. The probe has been out there for eleven years; it will wait.
