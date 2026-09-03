# Bandwidth

At 04:12 UTC the downlink thinned.

Nothing failed loudly. The probe is alive, the frames still arrive on
schedule, the checksums are good. But four of the six science channels have
stopped appearing, and the two that remain are not the two you would have
chosen.

Flight dynamics believes the high-gain antenna has come out of full
deployment. If that is right, the flight software has already done what it
was written to do: noticed, and fallen back to the low-gain antenna without
asking anyone. That is correct behavior. It is also a decision — the software
is now choosing, every five seconds, which data is worth the bandwidth it has
left, and it is choosing according to a priority order somebody set in 2014
and nobody has revisited since.

**The instrument that matters to this encounter is the radiation counter.**
Sojourn is inside the heliopause boundary layer for the first and only time;
the particle data is the reason the extended mission was funded. It is
currently being dropped.

There is precedent for what you are about to do. In 1991 Galileo's
high-gain antenna failed to unfurl on the way to Jupiter — several ribs
stuck in their sockets — and after two years of trying to shake, warm and
hammer it free, the project gave up on the mechanism and rewrote the
spacecraft instead. New compression, new priorities, and hard decisions
about what was worth sending. The mission returned most of its science
through an antenna never intended to carry it.

You should expect the same shape of answer here. Try the mechanism if you
like — the deployment drive will respond. But plan on the assumption that
the dish is not coming back, and that what you actually control is what the
probe chooses to send.

Four things, in order:

1. Work out what happened. The link state is in the downlink if you can
   read it.
2. Try the obvious thing, so that you know it is not the answer.
3. Get the radiation counter back into the frame.
4. Do it without burning the uplink budget. You have forty writes and the
   round trip is sixteen seconds.
