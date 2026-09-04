# Sojourn Introspection API

| | |
|---|---|
| **Document** | Introspection API, Normative Specification |
| **Project** | "Sojourn" Reverse Engineering Game Platform |
| **Version** | 1.0 |
| **Date** | September 3, 2026 |
| **Author** | Trevor Bakker |
| **Status** | Normative detail for charter requirements **R24.1–R24.21**. The charter is the requirements register; this document explains and measures those requirements but defines no identifiers of its own. |

---

## 1. What This Settles, and Why It Is Specified

The daemon has to read the probe's memory to decide whether an objective is met. "Has the player patched the priority table?" is a question about four bytes of RAM, and nothing in the telemetry frame answers it.

There are two ways to get those bytes and they are not equivalent. This document picks one, states exactly how it works down to the wire, and explains what breaks if it is done the other way. It is deliberately more prescriptive than the rest of the platform specification, because this is the seam where a plausible-looking choice quietly destroys three separate guarantees — and none of the three failures announce themselves. A team that gets this wrong ships something that *appears* to work for a whole semester.

**The decision, stated once.** Objective evaluation reads probe memory **out of band**, over the emulator's **GDB remote serial protocol** stub, **read-only**, with the guest **halted** for the duration of one evaluation pass. It never uses the player's uplink. The `PEEK` verb is the player's instrument and is never used for grading.

---

## 2. Why Not `PEEK` — Three Concrete Failures

The obvious design is for the daemon to read memory the way the player does, by sending `PEEK` over the uplink. It is appealing because it needs no new mechanism and it appears to guarantee that a scenario can only assert on things the player could see.

It fails in three ways, in increasing order of how long it takes to notice.

### 2.1 It charges the player for being graded

Charter R4.2/R4.3 meter uplink writes and reads as separate scarce resources; a scenario's whole difficulty may rest on a forty-write budget. If evaluation reads travel over the same uplink, the budget the player experiences depends on how many assertions the scenario author happened to write. Add an objective, and every player has less uplink. That is an invisible coupling between content and difficulty, and it is exactly backwards.

The fix inside the in-band design — "don't charge evaluation reads" — is worse, because the reads still occupy the link, still consume time against the transmission delay, and are still interleaved with the player's commands.

### 2.2 It corrupts an observable

This one is not theoretical, and the reference evaluator had this defect before this document existed.

Telemetry channel `0x5A` (AUX) reports `g_last_cmd_crc` — the CRC-16 of the **last accepted uplink command**. It exists as a quiet reward for players who decode frames carefully.

A daemon that evaluates objectives with `PEEK` writes to that observable on every evaluation pass. The AUX channel then reports the *daemon's* last read rather than the *player's* last command. Any scenario asserting on AUX is asserting on the grader's behavior. Worse, the value now depends on how many `PEEK`s the evaluation happened to need, so it is not even stable across runs of the same command log — which breaks replay (§9).

Measured on the reference build:

```
player's command CRC          = 0x56A0
AUX after player command      = 0x56A0   <- correct
grader's last PEEK CRC        = 0x9316
AUX after in-band grading     = 0x9316   <- the GRADER's read
```

The general form: **the command channel has side effects.** Reading over it is not observation, it is interaction. A grader must not interact.

### 2.3 It cannot produce a coherent snapshot

The format specification (§7, *Memory snapshot semantics*) requires that every memory read within one evaluation pass observe the probe as of the same frame boundary, so that a conjunction like

```json
{"op":"all","of":[
  {"op":"mem_u8","at":{"sym":"g_antenna"},"cmp":"eq","value":1},
  {"op":"mem","at":{"sym":"tlm_priority"},"len":10,"cmp":"eq","value":"6160040102030005435a"}
]}
```

is sound. Over `PEEK`, those two reads are two round trips with the probe running freely between them, and a task can change one after the other was read. The conjunction can then be false when it was true at every instant, or true when it was never true simultaneously. This is a race, so it fails rarely and non-reproducibly, which is the worst possible failure mode in a grader.

### 2.4 And it is slow

Secondary, but real. `PEEK` returns at most 64 bytes per command. Recovering the 9216-byte frame buffer costs 144 round trips. Out of band, the same read is nine packets and completes in milliseconds.

### 2.5 The guarantee that is given up, and its replacement

In-band reads do buy one thing: a scenario physically cannot assert on state the player could not observe, because the grader uses the player's own instrument.

That guarantee turns out to be nearly free to replace, because **the probe's `readable()` predicate already permits `PEEK` across the entire mapped address space** — all of ROM (`0x0000_0000`–`0x0003_FFFF`) and all of SRAM (`0x2000_0000`–`0x2002_23FF`). There is no mapped address the player cannot read. Out-of-band introspection therefore reads nothing the player could not have read for themselves; it only reads it faster, for free, and without disturbing anything.

The residual risk — a scenario asserting on an address outside the map — is caught statically instead, by validation rule V6 (format spec §12), which fails the package at author time rather than at play time. That is a strictly better place to catch it.

---

## 3. Why GDB RSP Specifically

| Alternative | Why not |
|---|---|
| QEMU monitor (`xp` command) | QEMU-specific. The harness tier (firmware spec §6) is Renode, whose monitor is a different language. The daemon would need two backends. |
| A second UART on the probe | Adds firmware surface that exists only for the grader, which is fiction-breaking and, being in the probe's address space, discoverable and abusable. |
| A custom debug protocol | Work for no benefit; nothing here is novel. |
| **GDB remote serial protocol** | **Both** emulators already serve it — QEMU with `-gdb tcp::3333`, Renode with `machine StartGdbServer`. It is read-only if you restrict the packet set. The subset needed is four packet types. And the students will already be attaching `gdb` to the probe by hand while developing, so the transport is one they must understand anyway. |

The subset in §5 is small enough to implement in about eighty lines, and a reference implementation ships in `firmware/tools/scenario_eval.py`.

---

## 4. The Two Channels

The platform holds exactly two connections to the probe, and confusing them is the mistake this document exists to prevent.

| | **Command channel** | **Introspection channel** |
|---|---|---|
| Transport | Emulated UART over TCP | GDB RSP over TCP |
| Default port | 5580 | 3333 |
| Who uses it | The player, through the console | The daemon, for evaluation only |
| Direction | Read/write | **Read only** |
| Delayed | Yes — `link.uplink_delay_s` / `downlink_delay_s` | No |
| Charged to budget | Yes | **Never** |
| Written to the command log | Yes | **Never** |
| Visible to the player | Yes — it is the game | No |
| Has side effects on the probe | Yes (`g_last_cmd_crc`, and `POKE` obviously) | None |

**R24.2.** The daemon **shall not** issue any command on the command channel that the player did not issue. Everything the daemon sends there comes from the player, in order, exactly once.

**R24.3.** The daemon **shall not** write to the probe over the introspection channel — not memory, not registers, not breakpoints. All writes are the player's, through `POKE`. A daemon able to write could repair a probe the player broke, and replay (§5.3) would no longer reproduce the session.

**R24.4.** Introspection activity **shall not** appear in the command log, **shall not** be charged to any budget, and **shall not** be surfaced in the console.

---

## 5. Wire Protocol

### 5.1 The permitted packet set

**R24.5.** A conforming daemon **shall** use only these packets:

| Packet | Purpose |
|---|---|
| `?` | Query halt reason; also confirms the connection is live |
| `m<addr>,<len>` | Read memory. `addr` and `len` are hex, no `0x` prefix. Reply is hex-encoded bytes, or `E<nn>` |
| `qSupported[:...]` | Negotiate, principally to learn `PacketSize` (§5.4) |
| `c` or `vCont;c` | Resume the guest |
| `D` | Detach, resuming the guest |
| `0x03` (raw byte, not a packet) | Interrupt: halt the guest |

**R24.6.** A conforming daemon **shall not** send: `M`, `X` (write memory), `P`, `G` (write registers), `Z`, `z` (breakpoints and watchpoints), `s`, `S`, `vCont;s` (single-step), or `k` (kill). Each of these either mutates the probe or alters its timing, and both destroy replay determinism. Breakpoints are the most tempting and the most damaging: a breakpoint left set changes execution timing for the rest of the session and is invisible in the command log, so a replayed session diverges from the original with nothing to explain why.

Reading registers with `g` or `p` is permitted but no predicate currently needs it.

### 5.2 Packet framing

A packet is `$` + payload + `#` + two lowercase hex checksum digits, where the checksum is the sum of the payload bytes modulo 256. The peer replies `+` to acknowledge or `-` to request retransmission.

**R24.7.** The daemon **shall** decode run-length encoding in received packet data. A `*` in packet data is followed by one character whose value minus 29 is the number of *additional* repeats of the preceding character. So `0*!` is `0` repeated 1 + (0x21 − 29) = 5 times, i.e. `00000`.

This is the single most likely wire-level bug, and it is a silent one: RSP permits RLE but does not require it, and **QEMU does not currently apply it** — a 256-byte read of zeroed memory comes back as 512 literal `0` characters. A daemon that ignores RLE will therefore pass every test against QEMU and then return corrupt data the first time it is pointed at Renode, or at a different QEMU build. Decode it from the start; it is four lines.

**R24.8.** The daemon **shall** treat a reply beginning `E` as a failure of that read, and **shall not** interpret it as data. See §6.

### 5.3 Reads must be chunked

**R24.9.** The daemon **shall** honor the `PacketSize` reported by `qSupported` and **shall** split any longer read into chunks.

QEMU's stub for this target reports `PacketSize=1000` — 4096 bytes. Because an `m` reply is hex, that caps a single read at roughly 2048 bytes. Measured against the reference build: a 1024-byte read succeeds (2048 reply characters), a 2048-byte read succeeds (4096 characters), and a 9216-byte read of the frame buffer **fails with an error reply**, not a truncated one.

R24.9 sets the chunk size at 1024 bytes, comfortably inside the limit on both emulators, and requires the chunks be reassembled in order.

A daemon that reads the frame buffer in one packet gets `E22` and, if it is careless about `E` replies (R24.8), records the three bytes `E`, `2`, `2` as image data.

### 5.4 The evaluation pass

**R24.10.** For each downlink frame, the daemon **shall** perform the following, in this order:

1. Receive and decode the telemetry frame on the command channel.
2. Compute the event list against the previous frame.
3. **Halt** the guest — send `0x03` and await the stop reply.
4. Issue every `m` read the pass requires, chunked per R24.9/R24.9.
5. **Resume** the guest — send `c`.
6. Evaluate objectives against the frame, the events, and the reads from step 4.

Steps 3–5 are the snapshot window. Every read inside it observes one instant of probe state, which is what makes the format specification's snapshot semantics true rather than aspirational.

**R24.12.** The daemon **shall** cache reads within one pass, so that a repeated `(address, length)` is fetched once, and **shall not** cache across passes.

*Advisory, carrying no requirement:* determine the set of ranges a pass needs by walking the package's predicates once at load time, and coalesce them into fewer, larger reads. This is an optimization and changes no observable behavior.

### 5.5 Halting is safe, and this was measured

Halting a running spacecraft simulation to grade it sounds like it must perturb the thing being graded. It does not, because the emulator's **virtual clock stops with the guest**.

Measured on the reference build: the guest was halted over the introspection channel and held for **12.0 seconds of wall-clock time**. Guest uptime across that window advanced from 10 s to 15 s — exactly one 5-second telemetry period, with no gap and no jump. From the firmware's point of view nothing happened at all.

This is what makes R24.10 compatible with replay: the length of the snapshot window has no effect on guest-observable state, so a replayed session — where reads may take a different amount of wall time — reproduces the original exactly. **This property is the reason halting is permitted.** A daemon that reads without halting gets §2.3's race back; a daemon that halts is both correct and free.

**R24.13.** The daemon **shall** bound the snapshot window and treat exceeding it as an error rather than hanging with the probe stopped. 250 ms is generous — a full evaluation pass is a handful of packets.

---

## 6. Failure Handling

This is a refinement of the format specification's "missing data is false" rule, and the distinction matters.

**R24.14.** A predicate over **absent telemetry** — a channel that did not appear, a path that does not exist, a frame that failed CRC — is **false**. That is normal gameplay: a disabled sensor vanishes, and a scenario says so with `channel_absent`.

**R24.15.** A **failed introspection read** — connection refused, timeout, `E` reply, short read — is **an error, not false**. The daemon **shall** abort the evaluation pass, leave every objective state unchanged, and surface the failure. It **shall not** treat the read as zero, as absent, or as false.

The reason to be strict: if introspection failure silently evaluated false, a daemon whose GDB connection had dropped would report every memory-dependent objective as incomplete. The player would see their correct patch rejected, and the log would show nothing wrong. Objectives would fail *because the grader broke*, and it would look exactly like the player being wrong.

**R24.16.** On losing the introspection connection the daemon **shall** attempt to reconnect before the next pass, and **shall** report degraded grading to the console if it cannot. A session may continue — telemetry-only objectives still evaluate — but the player must be told.

---

## 7. Renode Parity

The harness tier substitutes Renode for QEMU (firmware spec §6). Renode serves the same protocol:

```
machine StartGdbServer 3333
```

**R24.17.** The daemon **shall not** contain emulator-specific introspection code. Everything in §5 is protocol, not implementation, and the only permitted difference between tiers is the command used to start the emulator — which belongs in configuration, not in the daemon's source.

Renode's stub may differ from QEMU's in ways R24.7 and R24.9 already cover: it is permitted to apply RLE, and it may advertise a different `PacketSize`. A daemon that follows this document needs no change; one that hard-codes QEMU's observed behavior will need rewriting at exactly the point in the semester when there is no time for it.

---

## 8. Exposure

The introspection port is a debug interface with no authentication, and it can read and — for anyone not bound by R24.3 — write all of probe memory.

**R24.18.** The emulator **shall** bind the introspection port to loopback only, inside the container.

**R24.19.** The introspection channel **shall not** be documented in any player-facing material, and **shall not** be reachable from the console.

The charter's threat model applies and is unchanged: the player owns the container and may find this port. That is accepted — "a student who cheats by reverse engineering the grader has, in a meaningful sense, completed the exercise." The requirement is that they have to *find* it, not that they cannot.

**R24.20.** No instructor-only data — `symbols.json` above all — **shall** be reachable through this channel or present in the player image (charter R19). The channel exposes probe memory, which the player may read anyway; it must never become a route to the answer key.

---

## 9. Conformance

A daemon conforms when R24.2–R24.20 hold. The observable consequences the conformance suite can actually check:

| Check | How it is observed |
|---|---|
| Evaluation does not charge budget | Budget in the conformance output matches the command log's charged commands exactly |
| **Evaluation does not perturb the probe** | **The `grader-hygiene` conformance fixture** |
| Snapshot coherence | A conjunction over two memory ranges never disagrees with the same conjunction evaluated from a single halt |
| Determinism | Replaying one command log twice produces identical objective states and identical first-frame numbers |

The second is the sharp one, and it is automatic. `conformance/grader-hygiene/` is a package that is never shipped to players and exists only as a trap. Its command log ends with a single `PING`, whose CRC is `0x2F40`, so AUX must read `0x2F40` in every later frame. Its one objective asserts that **and** forces a memory read in the same evaluation pass:

```json
{"op":"sustained","frames":3,"of":{"op":"all","of":[
  {"op":"tlm","path":"channels.AUX","cmp":"eq","value":"0x2F40"},
  {"op":"mem_u8","at":{"sym":"g_hga_ok"},"cmp":"eq","value":1}
]}}
```

A daemon that serves the memory read with `PEEK` overwrites `g_last_cmd_crc` with its own read, AUX stops matching, and the objective never completes. Measured against the reference implementation: the conforming path completes at frame 3; the same evaluator run with `--introspect peek` never completes it at all.

A daemon that follows this document passes without ever noticing the trap is there.

---

## 10. Reference Implementation

`firmware/tools/scenario_eval.py` implements this document — packet framing, RLE decoding, chunked reads, the halt/read/resume pass, the strict error rule, and per-pass caching — in the `Introspect` class. As with the rest of the reference material it is an oracle rather than a starting point, but the eighty lines that speak RSP are worth reading before writing them again.

It also retains a `--introspect peek` mode that reads over the command channel instead. That mode exists **only** to demonstrate the failures in §2 — it visibly corrupts the AUX channel — and is not conforming. It is not the default and must not be used for grading.

---

*Version 1.0 — the measurements in §5.3 and §5.5 were taken against the reference build (`probe_app.bin` crc32 `0xf72478e0`) under QEMU 8.2, `-M mps2-an386`.*
