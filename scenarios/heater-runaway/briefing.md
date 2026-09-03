# Cold Start

Sojourn is losing instruments, one at a time, and nobody commanded it to.

The camera went first. Two frames later the radiation counter stopped
reporting. Both are simply absent from the downlink now — not reading zero,
absent — and the probe has raised no fault. Whatever is doing this believes
it is behaving correctly.

Thermal has a theory. The survival heater appears to be running continuously,
which it should not be: the probe is warmer than its own switch-off point
and has been for years. A heater that never switches off is a heater that
never stops drawing power, and this spacecraft has a power manager whose job
is to keep total draw under a budget by turning things off. It is not
malfunctioning. It is doing exactly what it was told, in a situation nobody
anticipated.

So there are two things wrong and only one of them is the cause.

Stop the heater, and get the radiation counter back. Note that recovering an
instrument the power manager shed is a separate act from removing the reason
it was shed — put them back in the wrong order and you will simply watch it
be shed again.

The thermostat's parameters are not in the recovered manual. They are in the
running software, where everything else on this probe is.
