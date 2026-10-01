# TOPO Protocol Specification v1 (DRAFT)
Hop-by-hop custody store-and-forward with stop-and-wait ARQ on DECT NR+

| | |
|---|---|
| Status | Draft 0.1, for review |
| Target | Conexio Stratus Pro (nRF9151), NCS v3.2.1 |
| Workload assumption | **Nominal**: 1 pkt/s aggregate, 64 B payload, 5 min outage target |
| Keywords | MUST / SHOULD / MAY as in RFC 2119 |
| Rule IDs | Each normative rule has an ID (e.g. `C3`) so tests can trace to it |

Values marked **(P)** are *provisional* and will be replaced by measured values (see Section 12).

---

## 1. Scope and Guarantees

- **G1** Per hop: at-least-once delivery via ACK/retry.
- **G2** To the application: effectively-once, via dedup within the dedup window.
- **G3** Ordering: FIFO per stream, where a stream is `(src_id, class)`. No ordering across classes.
- **G4** Custody: once a node sends `ACK(ACCEPTED)`, it is responsible for the packet until the next hop ACKs it.
- **G5** Volatile custody: a node reset loses stored packets. The loss MUST be *detectable* (Sections 9 and 11), not silent.
- **Non-goals for v1:** end-to-end ACK, routing (topology is static), encryption (space reserved), durable storage (interface reserved).

## 2. Node Identity and Roles

- `node_id` is 16-bit, `0x0000` invalid, `0xFFFF` broadcast. Testbed: A=14402, B=56992, C=44720.
- Roles: `SOURCE`, `RELAY`, `SINK`. A node MAY hold several roles.
- Static next-hop table: `dst_id -> next_id`, set via the shell and persisted to NVS.
- **Open item:** whether `node_id` equals the DECT short RD ID or is mapped onto it (Section 12).

## 3. Frame Format

All multi-byte fields are **little-endian**. Frames MUST be serialized and parsed field by field. Struct casting of `__packed` types is prohibited.

### 3.1 Common header (16 bytes)

| Off | Size | Field | Description |
|---:|---:|---|---|
| 0 | 1 | `ver_type` | `[7:4]` protocol version (=1), `[3:0]` type |
| 1 | 1 | `flags` | see 3.2 |
| 2 | 2 | `src_id` | Originating node |
| 4 | 2 | `dst_id` | Final destination |
| 6 | 2 | `prev_id` | Transmitter of this hop |
| 8 | 2 | `next_id` | Intended receiver of this hop |
| 10 | 2 | `seq` | Per-stream sequence number |
| 12 | 2 | `epoch` | Originator's boot epoch (DATA); see 3.4 for other types |
| 14 | 1 | `hops` | Incremented at each relay |
| 15 | 1 | `ttl` | Hop limit, default 5, decremented at each relay |

Types: `1=DATA`, `2=HELLO`, `3=ACK`, `4=PROBE`. Other values are reserved.

### 3.2 Flags

| Bit | Name | Meaning |
|---:|---|---|
| 0 | `CUSTODY_REQ` | Sender requests custody (MUST be 1 for DATA in v1) |
| 1 | `RETX` | Retransmission of an earlier attempt |
| 3:2 | `CLASS` | `00`=Telemetry, `01`=Alarm, `10`/`11` reserved |
| 4 | `SEC` | Reserved for authentication. MUST be 0 in v1 |
| 7:5 | reserved | MUST be 0 on TX, ignored on RX |

**F1** A receiver MUST drop frames with an unknown `ver`, a reserved `type`, or `SEC=1`, and count them (`rx_bad_hdr`).
**F2** Frames shorter than their type's minimum size MUST be dropped and counted.
**F3** `MAX_PAYLOAD` = MTU - 16. If the 249 B figure is the total PHY payload, `MAX_PAYLOAD` = **233 (P)**.
**F4** When security is added, the nonce will be `(src_id, epoch, seq, class)`, which is unique per packet by construction.

### 3.3 Type-specific payloads

| Type | Payload | Total |
|---|---|---:|
| DATA | 0..`MAX_PAYLOAD` application bytes | 16..249 |
| HELLO | `role`(1), `free_pct`(1) | 18 |
| PROBE | none | 16 |
| ACK | `status`(1), `queue_free`(2), `node_epoch`(2) | 21 |

### 3.4 Field usage by type

- **DATA:** `src_id`/`epoch`/`seq`/`class` identify the packet end to end and are never modified by relays. `prev_id`, `next_id`, `hops`, `ttl` are rewritten at each hop.
- **HELLO / PROBE:** `src_id`=`prev_id`=sender, `epoch`=sender's current epoch. HELLO uses `next_id=dst_id=0xFFFF`. PROBE uses `next_id`=target and `seq` as a nonce.
- **ACK:** `src_id`, `epoch`, `seq`, `class` echo the DATA being acknowledged. `prev_id`=acker, `next_id`=the DATA's transmitter. The acker's own epoch travels in `node_epoch`.

### 3.5 ACK status codes

| Code | Name | Custody transferred? |
|---:|---|:---:|
| 0x00 | `ACCEPTED` | Yes |
| 0x01 | `DUPLICATE` | Yes (already held or already forwarded) |
| 0x02 | `QUEUE_FULL` | No |
| 0x03 | `TTL_EXPIRED` | No (packet is discarded and counted) |
| 0x04 | `NO_ROUTE` | No |
| 0x10 | `PROBE_REPLY` | n/a |

`queue_free` = free slots available **to the class of the ACKed packet** at the acker.

## 4. Timing and ARQ

**A1** Each node keeps **one DATA frame in flight per next hop** (stop-and-wait), shared across classes.
**A2** After TX, the sender arms an RX window for the ACK. Preferred: a fixed offset from TX-complete in modem time. Fallback: an open window of `ACK_TIMEOUT`.
**A3** An ACK matches only if `prev_id == next_id_of_sent`, `src_id`, `epoch`, `seq` and `class` all match the frame in flight. Other ACKs are ignored and counted (`rx_stale_ack`).
**A4** On timeout, retransmit with `RETX=1` and the **same** `seq` after a backoff. Backoff is uniform random in `[BACKOFF_MIN, BACKOFF_MAX]`, with the range doubling per attempt up to `BACKOFF_CAP`.
**A5** After `MAX_TX_ATTEMPTS` failed attempts, the packet is **not** discarded. It stays in the store and the link transitions to `DOWN` (Section 8).
**A6** An ACK with `QUEUE_FULL` or `NO_ROUTE` is *not* a timeout. The packet stays, and the sender holds off that class for `NACK_HOLDOFF`, scaled up if `queue_free` = 0. An alarm holdoff MUST NOT block telemetry, and vice versa.
**A7** After every completed exchange, an outbound-active node MUST keep RX armed for at least `INTER_TX_LISTEN` before its next TX, so inbound frames (e.g. new ingress while draining) are not starved. This resolves the half-duplex arbitration.

## 5. Custody Rules

**C1 Store-first.** Every DATA frame a relay accepts goes into the store *before* it is ACKed. There is no separate cut-through path. A packet on an empty queue is simply eligible for immediate transmit. This removes the ordering hazard of mixing cut-through and queued traffic.
**C2** A relay MUST send `ACCEPTED` only after `store.put` returned 0, or completed with success if it returned `-EINPROGRESS`.
**C3** A node deletes a stored packet (`store.pop`) **only** upon `ACCEPTED` or `DUPLICATE` from its next hop.
**C4 Sink.** If `dst_id == self`, the node calls `deliver()` to the application and **then** ACKs. Sinks do not use the store.
**C5** A source application `send()` returns success only when its own store has accepted the packet. Otherwise the app gets an error (backpressure to the app).
**C6** On `TTL_EXPIRED` the receiver discards the packet and counts it. The sender treats it as a declared drop and pops the packet.
**C7** Relay: `ttl` is decremented and `hops` incremented **when the frame is enqueued for the next hop**, not at each retry.

## 6. Deduplication

**D1** Each receiver keeps a stream table with up to `MAX_STREAMS` (16, P) entries `{src_id, class, epoch, last_seq, last_seen_ms}`.
**D2** For an arriving DATA frame in the same `epoch`, let `d = (int16)(seq - last_seq)`:
- `d <= 0`: **duplicate**. Reply `ACK(DUPLICATE)`, do not enqueue or deliver again.
- `d >= 1`: **new**. Accept, set `last_seq = seq`, and if `d > 1` record `gap = d - 1` as `rx_gap` (Section 11).

**D3** If the frame's `epoch` is *newer* (serial arithmetic) than the stored one, treat it as a new epoch: accept, reset `last_seq = seq`, and emit `SRC_RESET(src_id, old, new)`. If *older*, discard, reply `DUPLICATE`, and count `rx_stale_epoch`.
**D4** Stop-and-wait per hop guarantees in-order arrival per stream, so `last_seq` is sufficient and no bitmap window is needed.
**D5** Entries idle longer than `STREAM_IDLE` are evicted. If the table is full, evict the least recently seen and count `stream_evictions`. This is an accepted, counted risk: a duplicate arriving after eviction of its stream would be treated as new.
**D6** Serial-number comparison MUST be used for `seq` and `epoch`. The wraparound test is mandatory.

## 7. Store and Queue Policy

### 7.1 Store interface (RAM implementation only in v1)

```c
enum sf_durability { SF_VOLATILE, SF_DURABLE };

struct sf_store_ops {
    const struct sf_store_caps *(*caps)(void *ctx);
    int  (*put)(void *ctx, const struct sf_pkt *p, uint32_t token); /* 0, -EINPROGRESS, or error */
    int  (*peek)(void *ctx, uint8_t cls, struct sf_pkt *out);
    int  (*pop)(void *ctx, uint8_t cls);
    int  (*expire)(void *ctx, uint64_t now_ms);
    void (*stats)(void *ctx, struct sf_store_stats *out);
    int  (*recover)(void *ctx);
};
void topo_on_put_done(uint32_t token, int rc);   /* async stores only */
```

**Q1** The core MUST NOT assume `put` is synchronous. The simulator provides a RAM store variant that randomly returns `-EINPROGRESS` to exercise this path.
**Q2** Time is a 64-bit millisecond uptime. 32-bit microsecond timestamps MUST NOT be used for expiry (they wrap after ~71 min).

### 7.2 Capacity (64 KB budget, Kconfig-tunable)

| Pool | Slot | Payload cap | Slots | Alarm-reserved | Memory |
|---|---:|---:|---:|---:|---:|
| Small | 80 B | 64 B | 512 | 64 | 40 KB |
| Large | 256 B | 240 B | 96 | 16 | 24 KB |

Payloads go to the smallest pool that fits. Slot metadata is 16 B (P), with `static_assert` on all sizes.
Survivable outage at Nominal, with 1.5x safety: 512 / (1 x 1.5) ≈ **5.7 min** (Telemetry alone: 448 / 1.5 ≈ 5.0 min).

### 7.3 Classes and policy

| | Alarm | Telemetry |
|---|---|---|
| Drain order | First | After alarms |
| Slot access | Reserved slots, plus any free slot | Non-reserved slots only |
| Overflow | Never dropped: `ACK(QUEUE_FULL)`, sender keeps packet | `reject` (default) or `drop_oldest` |
| Expiry | None | `TELEMETRY_TTL` (600 s, P), counted `dropped_expired` |
| Sequence space | `(src_id, ALARM)` | `(src_id, TELEMETRY)` |

**Q3** Within a class the store is strict FIFO. Across classes, Alarm is dequeued first. A frame already in flight is never pre-empted.
**Q4** `drop_oldest` applies to Telemetry only. Each drop MUST emit `CUSTODY_BROKEN(src_id, seq)` and count `dropped_overflow`, since the dropped packet was already ACKed.
**Q5** Expiry is evaluated at dequeue and at a low-rate periodic sweep. Expired packets are counted, never sent.
**Q6** Runtime policy switch: `exp sett sf_policy <reject|drop_oldest>`.
**Q7** Sources MUST rate-limit Alarm generation with a token bucket (`ALARM_RATE` 5/s, `ALARM_BURST` 10; P). Excess is rejected to the application.

## 8. Link Management (per next hop)

### 8.1 States

| State | Meaning |
|---|---|
| `UP` | Next hop reachable. Transmit from the store while non-empty (this is "draining" when a backlog exists) |
| `DOWN` | No DATA transmitted. Store keeps accepting ingress |
| `PROBING` | Reachability evidence seen. Verifying with PROBEs |

### 8.2 Transitions

| From | To | Trigger |
|---|---|---|
| `UP` | `DOWN` | `MAX_TX_ATTEMPTS` exhausted on a packet (A5), or no HELLO from that neighbor for `HELLO_DEAD` |
| `DOWN` | `PROBING` | Hold-down elapsed **and** (HELLO heard from next hop **or** `T_PROBE` timer fires) |
| `PROBING` | `UP` | `N_UP` **consecutive** PROBE replies, spaced `PROBE_FAST` |
| `PROBING` | `DOWN` | Any PROBE unanswered after `MAX_TX_ATTEMPTS` |

**L1** A HELLO means *maybe reachable in one direction*. It MUST NOT move the link to `UP` directly.
**L2 Hold-down.** After each `UP -> DOWN` transition, re-entry to `PROBING` is barred for `HOLDDOWN`. It starts at `HOLDDOWN_MIN` and doubles for each down-transition within the last 60 s, up to `HOLDDOWN_MAX`. It resets after 60 s of stable `UP`.
**L3** Ingress accepted while `DOWN` or `PROBING` goes to the store per Section 7. Ordering is unaffected because everything passes through the store (C1).
**L4** Only nodes with role `SINK` or `RELAY` emit HELLO, every `HELLO_PERIOD` with ±10% jitter. Probing is used when no HELLO is expected or heard.

## 9. Boot Epoch

**E1** At boot, before any radio activity, read the 16-bit epoch from NVS, add 1 (mod 2^16), write it back, and use the new value. On first boot (no NVS entry), initialize from the hardware RNG.
**E2** Every node tracks its neighbors' last-seen epoch from HELLO, PROBE and ACK (`node_epoch`). A change emits `NEIGHBOR_RESET(id, old, new)`.
**E3 Boot-loop guard.** If more than 5 boots occur within 5 min, delay radio start by `2^k` s (k = consecutive excess boots, capped at 60 s). This protects NVS wear and the channel.
**E4** The epoch NVS entry shares the partition with `exp save` profile writes. Their writes count against the same wear budget.
**E5** After an `NEIGHBOR_RESET` of the next hop, the sender SHOULD move that link to `PROBING`, since queued state at the neighbor is gone.

## 10. Configuration Parameters

| Parameter | Default | Notes |
|---|---|---|
| `HELLO_PERIOD` | 2 s | ±10% jitter |
| `HELLO_DEAD` | 7 s | ≈ 3 missed HELLOs |
| `ACK_TIMEOUT` | 40 ms **(P)** | Set from measured p99.9 RTT |
| `MAX_TX_ATTEMPTS` | 4 | 1 + 3 retries |
| `BACKOFF_MIN` / `MAX` / `CAP` | 10 / 20 / 80 ms | (P) doubling per attempt |
| `NACK_HOLDOFF` | 1 s | (P) |
| `INTER_TX_LISTEN` | 20 ms | (P) |
| `T_PROBE` | 3 s | ±10% |
| `PROBE_FAST` | 200 ms | (P) |
| `N_UP` | 3 | Consecutive probe replies |
| `HOLDDOWN_MIN` / `MAX` | 5 s / 60 s | |
| `TELEMETRY_TTL` | 600 s | |
| `STREAM_IDLE` | 1800 s | |
| `MAX_STREAMS` | 16 | |
| `ALARM_RATE` / `BURST` | 5/s / 10 | |
| Hop `ttl` default | 5 | |

## 11. Observability and Loss Accounting

### 11.1 Events (emitted to the log ring buffer and shell)

`TX`, `RX`, `ACK_RX`, `RETRY`, `LINK_STATE(id, old, new)`, `STORED`, `DRAINED`, `DROP_OVERFLOW`, `DROP_EXPIRED`, `CUSTODY_BROKEN`, `NEIGHBOR_RESET`, `SRC_RESET`, `RX_GAP(src, class, n)`, `NACK_RX`, `BAD_FRAME`.

### 11.2 Counters (per node, per class where relevant)

`generated`, `delivered`, `stored_total`, `drained_total`, `queue_peak`, `dropped_overflow`, `dropped_expired`, `rejected_full`, `retries`, `dup_rx`, `rx_gap`, `rx_bad_hdr`, `rx_stale_ack`, `stream_evictions`, `epoch`.

### 11.3 Conservation equation

For each stream over a test run:

```
generated = delivered + dropped_overflow + dropped_expired + rejected_at_source
          + inferred_reset_loss + still_stored + in_flight
```

`inferred_reset_loss` is the sum of sink-side `RX_GAP` events that coincide with a `NEIGHBOR_RESET` or `SRC_RESET`. Any residual is an **undeclared loss and is a defect**.

## 12. Verification Hooks and Open Items

### 12.1 Invariants (asserted in the simulator and in HIL log analysis)

| ID | Invariant |
|---|---|
| I1 | No undeclared loss after `ACCEPTED` (conservation equation balances) |
| I2 | No duplicate delivery to the application within the dedup window |
| I3 | FIFO per stream at the sink |
| I4 | Queue occupancy never exceeds capacity, and reserved slots are never taken by Telemetry |
| I5 | Liveness: if the link is stable for `T_stable`, the queue drains to zero |
| I6 | Link never enters `UP` without `N_UP` consecutive probe successes |
| I7 | `seq` and `epoch` wraparound never causes a false duplicate or false loss |

### 12.2 Open items (to close before freezing v1)

1. Measure: DATA and ACK airtime per MCS, TX-to-RX switch time, ACK RTT distribution, and set `ACK_TIMEOUT`, `INTER_TX_LISTEN` from data.
2. Confirm 249 B is the total PHY payload, and therefore `MAX_PAYLOAD`.
3. Confirm whether the modem API exposes DECT NR+ HARQ feedback, and whether it can replace part of the hop ACK.
4. Decide `node_id` mapping to DECT short RD ID.
5. Confirm the real workload behind the Nominal assumption.
6. Confirm 64 KB fits after `ram_report` (modem buffers, 32 KB log ring, app).
7. Review the Alarm reserved-slot split (80 of 608) against real alarm rates.

### 12.3 Deferred by design

| Item | Hook in v1 |
|---|---|
| Authenticated encryption | `SEC` flag, nonce definition F4, header/trailer room |
| Durable flash custody | `sf_store_ops` (`put` async, `recover`, `caps`) |
| OTA and version negotiation | 4-bit `ver` field |
| Relay power scheduling | RX arming through `topo_ports` |
