# NR+ Store-and-Forward Outage Report

**Project:** Conexio Stratus Pro — DECT NR+ evaluation
**Firmware:** `experiments/06_store` (hop custody, stop-and-wait ACK, RAM store)
**SDK:** nRF Connect SDK v3.2.1
**Data:** `data/06_store/20260930_233203/`
**Date of measurement:** 2026-09-30, host clock 23:32–23:47
**Procedure:** [`docs/06_store_and_forward/PROCEDURE.md`](../../docs/06_store_and_forward/PROCEDURE.md)

---

## 1. Scope

Hop-by-hop custody asks one node to hold custody of a frame until the downstream hop explicitly accepts it. Outage resilience asks the relay to continue buffering ingress traffic while the sink or gateway is offline, and subsequently drain that backlog strictly in FIFO order once connectivity recovers. An extended outage must fill the buffer, reject new ingress gracefully without corrupting existing custody, and resume ordered drain upon restoration.

This report is one automated run of that sink-outage case: 30 s healthy, sink stopped for 3 min, drain, sink stopped for 5 min, drain. Payload is 16 bytes because larger sizes are rejected by a codec bug described in §6. The run does not cover relay reboot, `drop_oldest`, or a 64-byte payload.

## 2. Setup

| Label | `device_id` | Port | Role |
|---|---|---|---|
| Source | 56992 | `socket://10.0.0.139:7777` | Generates 1 packet/s, `direct off`, next hop 44720, dest 14402 |
| Relay | 44720 | `socket://10.0.0.139:7778` | Holds custody until the sink ACKs |
| Sink | 14402 | `COM7` | Delivers, and is the node that is stopped |

Carrier 1711 on all three (`overlay-us.conf`). Epochs for this boot: source 22549, relay 22641, sink 22653. No reboot during the run.

Shell forced before start, on every board, even where the role already matched: `size 16`, `interval 1000`, `count 0`, `assume_up off`, `ack_timeout 400`, `policy reject`. Stores were flushed. `exp status` before start: `running=0`, `depth=0` on all three.

The sink's `delivered` counter is reset by each `exp start`. Figures below that say "status" are the counter at that snapshot. The sequence totals are counted from `DELIVER` lines and do not reset.

## 3. Result

The sink delivered sequence **0 through 887** (888 frames), strictly in order, with no missing number and no inversion. During both intervals where the sink was stopped, the sink log has **zero** `DELIVER` lines. The run log contains no `BAD_FRAME`, `RX_GAP`, `CUSTODY_BROKEN`, `DROP_OVERFLOW`, `DROP_EXPIRED`, or `NEIGHBOR_RESET`.

| Phase | Sink stopped | Relay store at the end of the stop | Source store at the end of the stop | Sink deliveries while stopped | Drain after the sink returned |
|---|---|---|---|---|---|
| Healthy | no | depth 0, peak 2 | depth 1, peak 3 | — | seq 0–47 in ~47 s (about 1 pkt/s) |
| 3 min | 23:33:17 → link `UP` 23:36:37 | **depth 180, peak 180** | depth 1 (the in-flight frame only) | 0 | seq 48–410, 363 frames in 165 s (2.2 pkt/s) |
| 5 min | 23:39:25 → link `UP` 23:44:47 | **depth 288, peak 288** | depth 9, peak 9 | 0 | seq 411–887, 477 frames in 164 s (2.9 pkt/s) |

288 is the telemetry cap: 320 small slots with 32 reserved for alarms. The 5-minute stop is longer than that shelf at 1 pkt/s, so the relay answered `QUEUE_FULL` for sequence **699** (13 `ACK_RX` and 13 `NACK_RX` on the source, 23:44:15–23:44:45). Policy `reject` left 699 in the source store. New frames queued behind it (source depth 9). Nothing was deleted.

After the second drain the snapshots, taken while one frame was still in flight, were:

| Node | Counters |
|---|---|
| Source | generated 884, drained 883, depth 1, in flight 1, peak 32 |
| Relay | stored 885, drained 885, depth 0, peak 288 |
| Sink status | delivered 475 since the last `exp start` |
| Sink log | 888 `DELIVER` lines, seq 0–887 |

475 is seq 411–885, two short of the log because the status line was printed before the last two deliveries. It is not a loss. The source peak of 32 (up from 9 at the end of the outage) is the queue growing while the relay's single in-flight frame was busy draining toward the sink; it was back to one frame by the final status.

Relay `LINK_STATE` lines during the stops are the probe cycle: `DOWN` after `max_attempts`, then `PROBING` on HELLO, then `DOWN` again, until the sink answers and the link goes `UP` (about 20 s after the 180 s and 300 s stops end). That is the hold-down and `n_up=3` gate, not a second failure.

## 4. What the phases show

**Healthy path.** Frames cross source → relay → sink at the generate rate. Relay depth stays at 0–2. Custody is not a 2-second hold; the hop cost is one ACK round trip.

**Three minutes with the sink gone.** The source does not accumulate the backlog. It hands each frame to the relay and deletes it on `ACK(ACCEPTED)`. The relay's depth tracks the outage (180 frames, one per second). When the sink returns, those frames are delivered in the same sequence order, and generation that continued during the drain is appended after them (seq 48 then 49, with no hole and no reorder).

**Five minutes.** The relay fills the telemetry pool (288) and refuses the head frame. The source keeps it and the frames generated behind it. Restoring the sink drains seq 411 onward in order, including the frames that were refused and retried. Declared refusal, not a silent drop.

## 5. Conservation

For this boot epoch, every sequence the sink delivered is exactly `{0, 1, …, 887}`.

The three `exp status` blocks are not taken at the same instant, and the sink counter restarts when the sink is started again, so `generated`, `drained`, and `delivered` are not expected to be one integer. They sit within a few frames of each other, which is the in-flight frame plus the lines that arrived while status was being printed. The sequence set is the check that matters: no hole, no duplicate `DELIVER`, no drop event.

## 6. Limits of this run

- **Payload is 16 bytes, not the 64-byte nominal.** `size 48` and `size 64` make the modem return a padded slot. The DATA decoder uses `buffer_len - 16` as the payload length, logs `BAD_FRAME`, and ACKs `QUEUE_FULL` on an empty store. The earlier captures `tools/logger/sf_a.txt`, `sf_b.txt`, and `sf_c.txt` failed for that reason. The production change is a 2-byte length in the DATA body and no `QUEUE_FULL` for "buffer too big." It is not in this image.
- **`ack_timeout` is 400 ms for this run**, set by the script so the window covers the ~200 ms RTT seen on the bench. It is not yet frozen from a 1-hop percentile capture.
- **Not run:** 100-packet 1-hop, relay reboot, relay powered off for 5 minutes, `drop_oldest`.

## 7. Conclusion

On a live three-node path at 1 packet/s and a 16-byte payload, the relay kept the sink outage in RAM, refused overflow without dropping custody, and delivered the entire sequence in order after both a 3-minute and a 5-minute stop. Undeclared loss in this capture is zero.
