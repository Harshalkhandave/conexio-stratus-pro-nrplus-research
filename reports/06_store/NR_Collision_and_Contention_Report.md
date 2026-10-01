# DECT NR+ Collision, Contention, and LBT Analysis Report

**Project:** Conexio Stratus Pro (nRF9151) — DECT NR+ Store-and-Forward Evaluation  
**Experiment:** `experiments/06_store` (Hop Custody, Stop-and-Wait ARQ, RAM Store)  
**Dataset:** `data/06_store/20260930_233203/` (Raw logs: `source.txt`, `relay.txt`, `sink.txt`, `report.txt`)  
**Date of Measurement:** 2026-09-30, host clock 23:32:03 to 23:47:00 (15 minutes / 900 seconds)  
**SDK:** nRF Connect SDK v3.2.1 / Zephyr RTOS  

---

## 1. Executive Summary

This study analyzes radio packet collisions, channel contention, and Listen-Before-Talk (LBT) dynamics during the automated 15-minute store-and-forward benchmark. The benchmark included a 30-second healthy baseline, a 3-minute sink outage with subsequent backlog drain, and a 5-minute sink outage with subsequent backlog drain.

### Key Findings:
1. **Pure RF Wave Collisions are Extremely Rare:**
   - Across **4,265 total on-air transmissions**, physical radio waves overlapped within the packet transmission window (<= 2 ms) only **61 to 70 times** (~1.4% of transmissions).
   - Total physical time that radio waves were actively colliding in the air was **~91.5 milliseconds** (less than 0.1 seconds total over the entire 15-minute test, or **< 0.01%** of total runtime).
2. **100% of Concurrent Transmissions Passed LBT:**
   - The modem returned `LBT_CHANNEL_BUSY` (`err 1`) **0 times** across all nodes.
   - When concurrent transmissions occurred, both nodes entered their ~4.6 ms LBT listening periods simultaneously. Because both were listening, neither emitted RF energy, causing both LBT checks to pass.
3. **The Real Delay Driver is Half-Duplex Deafness, Not Wave Collisions:**
   - Of the **89 retries** logged on the Source node, only 30 (~34%) occurred within the 5 ms LBT vulnerability window.
   - The remaining 59 retries (~66%) were caused by **half-duplex asynchronous deafness**: the Relay was locked into waiting for the Sink's downstream ACK and could not legally switch to transmit mode to answer the Source.
4. **System Reliability Remained 100%:**
   - Despite contention and retries, **888 out of 888 frames** (sequences 0 to 887) were delivered to the Sink in strict sequence order with **zero undeclared loss**.

---

## 2. Transmission & Event Inventory

Analysis of raw millisecond timestamps from all three concurrent serial/socket streams:

| Metric | Source (`56992`) | Relay (`44720`) | Sink (`14402`) | Combined Total |
|---|---|---|---|---|
| **Total Logged Events** | 993 | 2,487 | 1,107 | 4,587 |
| **Total Radio Transmissions (TX)** | 904 | 2,254 | 1,107 | **4,265** |
| **Retries Logged (`RETRY:`)** | 89 | 233* | 0 | 322 |
| **LBT Aborts (`err 1`)** | 0 | 0 | 0 | 0 |
| **Delivered to Application** | 0 | 0 | 888 | 888 |

*\*Note: The majority of the 233 Relay retries occurred during the 3-minute and 5-minute sink outages, where the Relay repeatedly attempted to reach the offline Sink before transitioning the link to `DOWN`.*

---

## 3. Pure Wave Collision Analysis

On DECT NR+ at MCS 0, a 32-byte frame (`size 16` payload + 16-byte header) takes approximately **1.5 milliseconds** of active on-air transmission time. 

A **pure physical collision** occurs when two nodes turn on their power amplifiers and emit RF energy within <= 2 ms of each other, causing destructive interference at receiver antennas.

### Simultaneous Transmission Overlap:

| Node Pair | Overlap <= 2 ms (Direct Wave Collision) | Overlap <= 5 ms (LBT Vulnerability Window) | Overlap <= 10 ms | Overlap <= 20 ms |
|---|---|---|---|---|
| **Source <-> Relay** | **16** | **30** | 76 | 225 |
| **Relay <-> Sink** | **45** | **72** | 128 | 310 |
| **Source <-> Sink** | **9** | **18** | 41 | 114 |
| **Total Wave Collisions** | **~61 to 70** | **~102** | — | — |

### Physical Collision Duration Calculation:

- Total physical wave collision count: ~61 occurrences (Source-Relay and Relay-Sink direct interactions).
- Duration per collision: ~1.5 milliseconds.
- **Total Physical RF Collision Time:**
  `61 * 1.5 ms = 91.5 milliseconds (approx. 0.091 seconds)`
- **Percentage of 15-Minute Test:**
  `0.0915 seconds / 900 seconds = 0.0101%`

Physical radio waves were colliding for **one-hundredth of one percent** of the test.

---

## 4. The 5 ms LBT Vulnerability Window

The test configured `tx.lbt_period = NRF_MODEM_DECT_LBT_PERIOD_MAX` (110 symbols = 4.58 ms).

Examining the exact millisecond time delta between Source and Relay concurrent transmissions within this window reveals:

| Time Difference (Delta) | Occurrences | Physical Phenomenon |
|---|---|---|
| **0 ms** | **7** | Both nodes fired on the **exact same millisecond**. 100% destructive wave crash. |
| **1 ms** | **3** | Direct physical on-air overlap. 100% destructive wave crash. |
| **2 ms** | **6** | Tail/head physical wave overlap. |
| **3 ms** | **2** | Packet 1 on air while Packet 2 is finishing LBT. |
| **4 ms** | **5** | Sequential back-to-back contention. |
| **5 ms** | **7** | Near-misses at the edge of the 4.6 ms LBT window. |
| **Total <= 5 ms** | **30** | **100% passed LBT** |

### Why Did 100% of Concurrent Transmissions Pass LBT?
During the 4.6 ms window where Node A was listening, Node B was also listening. Neither node had turned on its transmitter yet. Because neither node was emitting energy, both measured the channel as clear (`< 0 dBm`) and proceeded to transmit simultaneously.

---

## 5. Half-Duplex Asynchronous Deafness (The Primary Delay Factor)

Of the **89 retries** recorded on the Source, 30 were accounted for by the <= 5 ms LBT vulnerability window. 

The remaining **59 retries (66%)** were caused by half-duplex operational locking:

```
Source A                       Relay B                        Sink C
   |                              |                              |
   |                              |------ DATA Forward --------->|
   |                              |   [Enters ACK_WAIT window]   |
   |                              |                              |
   |------ DATA Ingress --------->| (B is in RX waiting on C;    |
   |                              |  B cannot transmit an ACK    |
   |                              |  to A without aborting C)    |
   |                              |                              |
   |                              |<------- ACK(ACCEPTED) -------|
   |                              |                              |
   | [Source A Times Out (400ms)] |                              |
   | [Source A Backoff (10-20ms)] |                              |
   |                              |                              |
   |====== RETRY DATA ===========>|                              |
   |                              |                              |
```

### Why this happens:
1. When Relay B forwards to Sink C, B immediately opens an ACK wait window of up to 400 ms.
2. In accordance with firmware rules, Relay B cannot abort this modem operation mid-window. If it cancelled the receive to acknowledge Source A, it would forfeit Sink C's ACK and falsely declare the downstream link dead.
3. Source A's ACK deadline expires (400 ms).
4. Source A logs `RETRY: attempt=2`, applies random backoff (10–20 ms), and retransmits.
5. The frame is safely held in Source A's store until Relay B completes its cycle and returns an ACK.

This contention caused Source A's local buffer to temporarily climb to a **peak depth of 32 packets** while Relay B was draining its 288-packet backlog.

---

## 6. Drain Speed & Throughput Breakdown

During backlog draining, Relay B cleared packets at **2.2 to 2.9 packets per second**:

- **3-minute outage drain:** 363 frames in 165 seconds = **2.2 pkt/s** (454 ms per packet).
- **5-minute outage drain:** 477 frames in 164 seconds = **2.9 pkt/s** (344 ms per packet).

### Cycle Budget per Drained Packet:

| Component | Description | Time Contribution |
|---|---|---|
| **Downstream Handshake** | Relay LBT (4.6 ms) + DATA (1.5 ms) + Sink reaction (15 ms) + Sink ACK (6 ms) | ~30 to 50 ms |
| **Mandatory Listen Gap** | Relay RX pause (`inter_tx_listen`) to avoid starving upstream ingress | 20 ms |
| **Upstream Handshake** | Source LBT (4.6 ms) + DATA (1.5 ms) + Relay processing + Relay ACK (6 ms) | ~50 to 80 ms |
| **Contention & Backoff** | Asynchronous deafness retries, LBT overlaps, and backoff delays | ~150 to 200 ms |
| **Total Cycle Time** | **Sustained time to clear one packet while handling live ingress** | **~340 to 450 ms** |

---

## 7. Conclusions & Recommendations

1. **LBT and Random Backoff Are Highly Effective:**
   LBT prevented continuous carrier jamming, and exponential random backoff (10–80 ms) immediately broke lockstep collisions on the subsequent attempt.
2. **Collisions Account for Negligible Time:**
   Radio waves were actively colliding for less than 100 milliseconds in total across 15 minutes of heavy multi-hop traffic.
3. **Firmware Improvements for Next Revision:**
   - **Explicit Payload Length in Header:** Add a 2-byte length field in the DATA header so the receiver strips trailing modem slot padding, allowing full 64-byte payloads without store rejection.
   - **Adaptive Upstream ACK Slicing:** Reduce `rx_slice_ms` on the Sink from 15 ms to 8–10 ms to shorten the Relay's downstream wait time and reduce Source timeouts.
   - **Balanced Ingress/Egress Scheduling:** Dynamically adjust the 20 ms listen gap (`inter_tx_listen`) based on current backlog depth to balance drain throughput against upstream ingress.
