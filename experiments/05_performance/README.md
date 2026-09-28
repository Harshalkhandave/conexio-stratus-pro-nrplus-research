# Week 5 — Performance, Latency & Throughput Characterization (`05_performance`)

This directory documents the experimental framework, parameters, and results for **Week 5: DECT NR+ Performance, Latency & Throughput Characterization** on the Conexio Stratus Pro (Nordic nRF9151) platform.

---

## 1. Research Objectives

1. **Multi-Hop Latency & Jitter Baseline:** Quantify baseline packet transit time and arrival jitter comparing a 1-hop direct RF link against a 2-hop relayed link ($A \to B \to C$).
2. **Payload Scaling & Throughput:** Evaluate throughput and MAC efficiency across frame payload sizes from minimal control packets (18 bytes) up to maximum standard MTU (249 bytes).
3. **High-Rate Stress Sweep:** Determine queue resilience, buffer limits, and radio scheduling stability under rapid transmission rates by sweeping interval from $500\text{ ms}$ down to $10\text{ ms}$ ($>60\text{ packets/sec}$).
4. **Channel Capacity Limit:** Push DECT NR+ single-carrier capacity to maximum stress (249 bytes @ 10 ms interval) to determine channel limits, peak throughput, and verify zero modem/firmware lockups (`error 24577`).

---

## 2. Hardware Testbed & Node Roles

Three Conexio Stratus Pro physical dev kits (nRF9151) in non-secure domain:

```
[ Node A: Source ]  ======(Direct / Relayed)======>  [ Node B: Relay ]  ======(NR+ PHY)======>  [ Node C: Sink ]
   ID: 14402                                           ID: 56992                                 ID: 44720
   Role: source                                         Role: relay                               Role: sink
   Port: socket://10.0.0.139:7777                      Port: socket://10.0.0.139:7778             Port: COM6
```

- **Node A (Source, ID 14402):** Configurable packet generator running rate sweeps, variable payloads, and hop tracking.
- **Node B (Relay, ID 56992):** Intermediate router performing cut-through application-layer forwarding with sequence deduplication.
- **Node C (Sink, ID 44720):** Network termination point and telemetry logger recording arrival timestamps (`time_us`), RSSI, hop count, and sequence numbers.

---

## 3. Firmware Architecture

Week 5 uses the unified multi-hop firmware in **`experiments/03_topology`**, configured with high-performance enhancements:
- **32 KB Log Buffer:** Prevents log drop messages (`--- dropped ---`) under $>60\text{ pkt/s}$ bursts.
- **Synchronous Command Execution:** Command responses (`exp status`, `exp set`) use direct synchronous shell printing to eliminate command interleaving and timeouts during high-traffic runs.
- **Cut-Through Forwarding (`fwd_mode=cut_through`):** Forwards valid packets directly from the receive callback with minimal queue latency.
- **Microsecond Precision Timestamps:** Transmit and receive events log hardware microsecond timestamps (`time_us`) for precise jitter and turnaround measurements.

---

## 4. Experiment Suite Matrix

| Experiment | Dataset Directory | Key Parameters | Evaluated Metrics |
|---|---|---|---|
| **Test 1: Latency & Jitter Baseline** | [`data/05_performance/1-Hop_vs._2-Hop_Latency_Baseline`](../../data/05_performance/1-Hop_vs._2-Hop_Latency_Baseline) | 32 B payload, 500 ms interval, 1-hop direct vs. 2-hop relayed | Transit stability, inter-arrival jitter, RSSI delta (-47 dBm vs. -68 dBm) |
| **Test 2: Payload Scaling** | [`data/05_performance/Payload_Scaling___Maximum_Throughput`](../../data/05_performance/Payload_Scaling___Maximum_Throughput) | 18, 64, 128, 249 B payloads @ 100 ms interval | Throughput scaling (1.4 to 18.9 kbps), byte packing efficiency |
| **Test 3: Rate Stress Sweep** | [`data/05_performance/Rate_Stress_Sweep`](../../data/05_performance/Rate_Stress_Sweep) | 64 B payload, interval: 500ms, 200ms, 50ms, 20ms, 10ms | Queue overflow thresholds, PDR under high packet rates (up to 62.3 pkt/s) |
| **Test 4: Maximum Channel Stress** | [`data/05_performance/Stress_Maximum_Throughput`](../../data/05_performance/Stress_Maximum_Throughput) | 249 B max payload, interval: 50ms, 20ms, 10ms | Absolute peak goodput (**124.26 kbps** hardware / **126.64 kbps** host / **127.26 kbps** PHY), radio duty cycle, PHY stability |

> [!NOTE]
> Transmit `power` settings (e.g. `power 10`, `power 3`) represent an **integer power level index (0–13)** defined by the DECT NR+ Common PHY header field, not dBm. Received link quality is measured separately at the receiver as **RSSI in dBm**.

---

## 5. Summary Results & Highlights

- **Overall Packet Delivery Rate (PDR):** **99.86%** (1,398 delivered out of 1,400 sent across all tests).
- **Peak Goodput:** **124.26 kbps** application goodput (**126.64 kbps** host arrival; **127.26 kbps** PHY on-air rate) at 10 ms nominal cadence with 249-byte payload on single-carrier DECT NR+ (MCS 0).
- **Relayed Forwarding Stability:** 100% forwarding reliability through intermediate Node B with sub-0.1 ms arrival jitter standard deviation.
- **Firmware Reliability:** Zero buffer overruns, zero dropped serial log lines, and zero modem error 24577 lockups.

---

## 6. Artifacts & References

- **Technical Report:** [`../../reports/05_performance/NR_Performance_Report.md`](../../reports/05_performance/NR_Performance_Report.md)
- **Experimental Procedure:** [`../../docs/05_performance/PROCEDURE.md`](../../docs/05_performance/PROCEDURE.md)
- **Raw Datasets:** [`../../data/05_performance/`](../../data/05_performance/)
- **Analysis Tool:** [`../../tools/parser/parse_performance.py`](../../tools/parser/parse_performance.py)
- **Visualizer GUI:** [`../../tools/topology_visualizer/`](../../tools/topology_visualizer/)
