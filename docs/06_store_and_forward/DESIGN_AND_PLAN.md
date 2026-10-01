The plan below is the original scope. What the firmware actually does, including shell keys and the choices left open, is [`IMPLEMENTATION.md`](IMPLEMENTATION.md).

# 06_store — implementation plan

Hop-by-hop custody store-and-forward on the same three-node DECT NR+ bench as `03_topology`.
Protocol rules live in [`experiments/06_store/topo_protocol_spec_v1.md`](../../experiments/06_store/topo_protocol_spec_v1.md). This document is the firmware plan: what we keep, what we replace, and in which order.

| | |
|---|---|
| Firmware | `experiments/06_store/` (new application, do not keep editing `03_topology`) |
| Platform | Conexio Stratus Pro / nRF9151 ns, NCS v3.2.1, sysbuild, same region overlays |
| Bench IDs | A `14402` source, B `56992` relay, C `44720` sink |

## 1. Motto

Experiments 03–05 proved an open-loop application relay. It forwards, it heals its *configuration* after reset, and on a live path it delivers about 99.9% of packets. It does not keep a packet that the next hop cannot take.

The healing report states the hole directly: during a sink outage the upstream nodes keep transmitting, and those frames are gone. The forward path makes that worse under load. `03_topology` holds at most 8 frames (`TOPO_FWD_QUEUE_MAX`) and then logs `FORWARD_DROP reason=queue_full`. There is no ACK, so the sender never learns the drop. A relay reboot looks the same as a clean delivery.

**Phase 1 (Hop Custody)** makes one hop reliable. A node that accepts a frame owns it until the next hop accepts it. Retries use the same sequence number. Duplicates are not delivered twice. On a stable 1-hop and 2-hop path the conservation equation balances with zero undeclared loss.

**Phase 2 (Outage Buffering)** makes an outage survivable and accountable. While the next hop is down the store keeps accepting ingress. When the link returns, the backlog drains in order. A reset still loses RAM custody (v1 is volatile), but that loss shows up as `RX_GAP` / `NEIGHBOR_RESET` / `SRC_RESET`, never as a missing sequence with no event.

Nominal workload the store is sized for: **1 packet/s, 64-byte payload, about 5 minutes of outage**. Peak throughput from Experiment 05 (62 pkt/s, 249-byte frames) is a different firmware mode. This one optimizes custody and airtime per hop, not cut-through goodput.

## 2. What 03_topology does, and what changes

Keep the bench and the PHY bring-up. Replace the forwarding model.

| `03_topology` today | `06_store` |
|---|---|
| PHY init, carrier overlay, MCUboot, `exp` shell, NVS profile + autostart | Same pattern, new app |
| 16-bit id from the modem short RD id (`14402`, `56992`, `44720`) | `node_id` **is** that id. Spec open item 4 is closed |
| Fire-and-forget broadcast. `next_hop` is not on air | Header carries `prev_id` and `next_id`. A node forwards only if `next_id` is itself |
| Relay enqueues a copy and forgets it. Queue depth 8, drop on full | Store-first. `ACK(ACCEPTED)` only after `put` succeeds. Delete only after the next hop ACKs |
| Seen-set of 16 `(src, seq)` pairs, no epoch | Per-stream `(src, class, epoch, last_seq)`. Reset is detectable |
| Radio loop: transmit, then sit in RX for `RX_PERIOD_S` (2 s), then drain the forward queue | One half-duplex scheduler: TX, ACK window, short listen, back to RX. No 2 s poll |
| On-air bytes cast to `__packed struct topo_packet` | Field-by-field codec. No struct cast of a received buffer |
| Logs `TX` / `RX` / `FORWARD` / `DELIVER` | Same prefixes where the meaning matches, plus `ACK_RX`, `RETRY`, `LINK_STATE`, `STORED`, `RX_GAP` |
| Roles, RF, autostart in NVS | Same, plus the boot epoch counter in that partition |

`03_topology` stays the characterization image. Do not backport custody into it.

## 3. Tightening decisions (tighter than the draft spec)

These are implementation choices. The spec rules (G, A, C, D, Q, L, E, I) still hold.

1. **One frame on the air at a time.** The spec allows one DATA in flight per next hop. This radio is half-duplex and the Experiment 06 bench has one next hop, so v1 allows one in-flight DATA for the whole node. A second next hop waits. This is stricter than A1 and matches the modem.
2. **Store sized for the nominal outage, not the spec's 64 KB ceiling, until `ram_report` says it fits.** 5 min × 1 pkt/s = 300 frames. Default pool: **320 small slots × 80 B ≈ 25 KB**, of which 32 slots are alarm-reserved. Large (256 B) slots stay a Kconfig, default **0**, until a test sends more than 64 B. The spec table (512 + 96) remains the upper Kconfig range.
3. **Empty store still sends on the next scheduler tick.** Store-first (C1) removes the cut-through path. It must not add a queueing delay when the queue depth is one. The cost of a hop is one ACK round trip, not a 2 s RX period.
4. **Telemetry only on the first bench.** Alarm class, reserved slots, and `drop_oldest` exist in the store from the start so the layout does not change later. Baseline traffic is telemetry. Alarm rate-limit and preemption are extended outage tests.
5. **Static route, one command.** `exp route <dst_id> <next_id>`. No listening-based next-hop selection in v1. HELLO is a liveness hint (L1), not a route.
6. **Logs stay single-line and UART-safe.** Experiment 05 needed a 32 KB log ring because the shell dropped lines. Keep that. Do not print a line per backoff slot; print `RETRY` once per attempt and keep the rest in counters.

Provisional timers (`ACK_TIMEOUT` 40 ms, backoff, `INTER_TX_LISTEN`) stay provisional until phase 3 measures RTT. Do not invent final numbers in the firmware before that capture.

## 4. Firmware shape

```
experiments/06_store/
  CMakeLists.txt
  prj.conf                  # modem DECT PHY, shell, settings/NVS, log ring
  Kconfig                   # pool sizes, timers, default role
  overlay-us.conf
  overlay-eu.conf
  src/
    main.c                  # modem init, PDC callback, starts the scheduler thread
    sf_codec.c / .h         # serialize + parse. No packed cast
    sf_store.c / .h         # RAM sf_store_ops: put, peek, pop, expire
    sf_dedup.c / .h         # stream table, serial seq/epoch compare
    sf_link.c / .h          # UP / DOWN / PROBING per next hop
    sf_arq.c / .h           # the one in-flight frame, timeout, backoff, NACK holdoff
    sf_sched.c / .h         # half-duplex: RX armed, TX, ACK window, INTER_TX_LISTEN
    sf_shell.c              # exp commands
    sf_persist.c / .h       # role/RF/autostart profile + epoch
    sf_log.c / .h           # one-line events and the counter block
```

`main.c` in `03_topology` owns PHY, packet handling, and the TX loop. That split is the actual betterment: the modem callback only enqueues a parsed frame or an ACK match. The scheduler thread is the only place that calls TX.

### 4.1 Scheduler (replaces the 2 s RX loop)

States, one thread:

| State | What the radio does |
|---|---|
| `LISTEN` | RX armed. Accept ingress. If the link is `UP` and the store has a frame and nothing is in flight, build the next TX |
| `TX` | One DATA, HELLO, or PROBE. On TX-complete start the ACK window (DATA/PROBE) or return to `LISTEN` (HELLO) |
| `ACK_WAIT` | RX armed for `ACK_TIMEOUT`. Match A3. Late or foreign ACKs count `rx_stale_ack` |
| `GAP` | RX stays armed for `INTER_TX_LISTEN` so an ingress ACK or a new frame is not starved (A7) |

On ACK timeout: `RETX=1`, same `seq`, backoff A4, attempt count ++. At `MAX_TX_ATTEMPTS` the frame **stays in the store** and the link goes `DOWN` (A5). `QUEUE_FULL` / `NO_ROUTE` are holdoffs, not timeouts (A6). `TTL_EXPIRED` pops the frame (C6).

### 4.2 Store

RAM implementation of the spec's `sf_store_ops`. `put` is synchronous and returns 0 in v1, but callers must already tolerate `-EINPROGRESS` so a later flash store does not rewrite the ARQ path.

- Smallest pool that fits the payload.
- Strict FIFO inside a class. Alarm is peeked before telemetry. A frame already in flight is not preempted (Q3).
- Telemetry expiry at peek and on a slow sweep (`TELEMETRY_TTL`). Expired frames are counted and never sent (Q5).
- Telemetry overflow: `reject` by default (`ACK(QUEUE_FULL)` upstream, packet stays at the sender). `drop_oldest` is a shell switch and emits `CUSTODY_BROKEN` (Q4).
- Slot metadata is a checked `static_assert` size. No `malloc`.

### 4.3 Identity, route, boot

- `node_id` = the same 16-bit id `03_topology` already prints at boot. `0x0000` invalid, `0xFFFF` broadcast.
- Route table is `dst_id -> next_id`, shell-set, stored in the profile.
- Epoch: read NVS, add 1, write back, **then** start the radio (E1). First boot draws from the RNG. More than 5 boots in 5 min delays radio start (E3).
- Profile keys copied in spirit from `03_topology`: role, dest, power, mcs, interval, hello, autostart, plus `route` and `sf_policy`.

### 4.4 Shell

Same verbs as `03_topology`, plus the store/link knobs.

| Command | Meaning |
|---|---|
| `exp status` | Role, RF, epoch, link state, queue depth, in-flight seq, counters |
| `exp role / sett / start / stop / autostart / save / load / factory` | As in `03_topology` |
| `exp route <dst> <next>` | Static next hop. Cleared route → `ACK(NO_ROUTE)` |
| `exp sett sf_policy reject\|drop_oldest` | Telemetry overflow policy (Q6) |
| `exp sf` | Store stats: occupancy, peak, free-by-class, drops |

Stop the run before changing role, route, or RF. `exp save` is what makes autostart and the route survive reset. Toggling autostart in RAM does nothing across reboot until save — same rule as 04_healing.

### 4.5 Log lines

Human-readable, one event per line, `key=value`, little enough for the automated test logger. Minimum set:

```text
TX: node=… type=DATA seq=… src=… dst=… prev=… next=… hop=… ttl=… class=tel epoch=… retx=0 time=… time_us=…
RX: node=… type=DATA seq=… src=… prev=… next=… rssi=… hop=… epoch=…
ACK_TX: node=… status=ACCEPTED seq=… src=… epoch=… class=tel queue_free=…
ACK_RX: node=… status=ACCEPTED seq=… from=… rtt_ms=…
RETRY: node=… seq=… attempt=… backoff_ms=…
LINK_STATE: node=… next=… old=UP new=DOWN reason=max_attempts
STORED: node=… seq=… src=… class=tel depth=…
DELIVER: node=… seq=… src=… prev=… hops=… rssi=…
RX_GAP: node=… src=… class=tel n=…
NEIGHBOR_RESET: node=… id=… old=… new=…
SRC_RESET: node=… src=… old=… new=…
DROP_EXPIRED: / DROP_OVERFLOW: / CUSTODY_BROKEN: / NACK_RX: / BAD_FRAME:
SUMMARY: … generated=… delivered=… stored=… dropped_overflow=… dropped_expired=… rejected=… in_flight=…
```

`DELIVER` stays the sink application line so a later visualizer pass can reuse the 03/05 parsers. New tags are additive.

## 5. Build order

Each phase ends when its check passes on hardware or on the host test, not when the code compiles.

### Phase 0 — application skeleton

Copy the PHY init / activate / PDC callback shape and the NVS profile from `03_topology`. Boot to an idle shell. `exp status` prints `device_id` and epoch. No DATA yet.

**Done when:** three boards boot, ids match the bench, `exp save` + reset restores role and autostart.

### Phase 1 — codec and dedup (host-testable)

`sf_codec` and `sf_dedup` compile without the modem. A small host test feeds byte strings.

**Done when:** round-trip of DATA, HELLO, ACK, PROBE; short frames and bad version count as drops; seq and epoch wrap tests pass both directions (I7, D6).

### Phase 2 — RAM store

Pools, alarm reserve, FIFO, expiry, `reject` vs `drop_oldest`.

**Done when:** a host test fills the pool, proves telemetry cannot take an alarm-reserved slot (I4), and `drop_oldest` emits a custody-broken count.

### Phase 3 — 1-hop stop-and-wait

Source and sink only. Measure ACK RTT for the configured MCS and payload. Set `ACK_TIMEOUT` from the high percentile of that capture, then freeze it in Kconfig with a comment pointing at the capture.

**Done when:** 100 telemetry frames, every one `ACCEPTED`, conservation holds, no `RX_GAP` on a clean link (I1, I2, I3).

### Phase 4 — relay custody

Static route A→B→C. Direct A–C is not required; the header's `next_id` means an overheard frame is not a second delivery path.

**Done when:** 100 frames, B's `STORED` then `ACK_RX` from C, C delivers in order, B's queue returns to zero (I5). A full B store produces `ACK(QUEUE_FULL)` and A keeps the frame.

### Phase 5 — link state and outage

HELLO dead-interval, hold-down, PROBE, `N_UP` before `UP` (I6, L1, L2).

**Done when:** sink powered off for 60 s, A keeps generating into the store, no DATA TX while `DOWN`, sink returns, backlog drains in order. Relay reboot emits `NEIGHBOR_RESET` and the sequences lost in B's RAM appear as gaps, not as silent holes.

### Phase 6 — Outage validation runs

Procedure doc and captures under `data/06_store/`. Same automated serial logger as prior test suites. Visualizer support is a follow-on, not a gate.

| Run | What it proves |
|---|---|
| Clean 1-hop, 100 pkts | Phase 3, frozen `ACK_TIMEOUT` |
| Clean 2-hop, 100 pkts | Phase 4, FIFO at the sink |
| Sink off 60 s, then on | Backlog drain, no undeclared loss |
| Relay reboot mid-run | Volatile custody loss is counted |
| Nominal 5 min, relay down | Occupancy stays inside the 320-slot pool, then drains |
| `drop_oldest` forced overflow | `CUSTODY_BROKEN` equals the sink gap |

A Python check over the three logs evaluates the conservation equation in spec §11.3. A non-zero residual fails the run.

The first hardware run of the sink-outage case (30 s healthy, then 3 min, then 5 min, `size 16`) is recorded in [`reports/06_store/NR_Store_and_Forward_Report.md`](../../reports/06_store/NR_Store_and_Forward_Report.md). Collision and contention study: [`reports/06_store/NR_Collision_and_Contention_Report.md`](../../reports/06_store/NR_Collision_and_Contention_Report.md). Procedure: [`PROCEDURE.md`](PROCEDURE.md). Raw logs: `data/06_store/20260930_233203/`. The 1-hop freeze of `ACK_TIMEOUT`, the relay-reboot gap, and `drop_oldest` are still open.

## 6. Out of scope for this firmware

- End-to-end ACK (hop ACK is the mechanism)
- Durable flash custody (the `sf_store_ops` async return is the hook only)
- Encryption (`SEC` must be 0; frames with `SEC=1` are dropped)
- Autonomous routing, or any change to `03_topology` / `04_healing` images
- Visualizer and parser updates (after the log lines are stable)
- Chasing the 05_performance throughput number. Stop-and-wait will be slower per hop than cut-through; that is the trade for custody

## 7. Risks

| Risk | What we do |
|---|---|
| 25 KB store plus modem and log ring does not fit | `ram_report` in phase 0/2. Shrink slots before adding features. Large pool stays off |
| ACK window too short, false `DOWN` | Phase 3 measures RTT before any outage test |
| UART log flood during retry storms | One `RETRY` line per attempt, counters for the rest, 32 KB ring retained |
| Epoch wear on a boot loop | E3 delay, and epoch shares the existing settings partition rather than a new one |
| Overheard duplicates if someone runs without `next_id` filtering | Relay accepts DATA only when `next_id == self` |
