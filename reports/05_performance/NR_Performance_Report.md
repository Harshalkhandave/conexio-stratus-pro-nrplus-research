# NR+ Performance, Latency & Throughput Characterization Report

**Project:** Conexio Stratus Pro — DECT NR+ Evaluation  
**Firmware:** `experiments/03_topology` (with 32 KB Log Buffer & Cut-Through Forwarding)  
**SDK:** nRF Connect SDK v3.2.1  
**Dataset:** `data/05_performance/`  
**Date of Measurements:** 2026-09-27  

---

## 1. Executive Summary

This report documents the empirical evaluation of DECT NR+ (ETSI TS 103 636) on the Conexio Stratus Pro (Nordic Semiconductor nRF9151) platform, evaluating multi-hop transit latency, packet delivery ratio (PDR), payload scaling, high-rate stress, and peak channel throughput.

### Key Highlights
- **Overall Reliability:** Across four comprehensive benchmark runs involving **1,400 transmitted packets**, the network achieved **1,398 delivered packets** (**99.86% overall PDR**).
- **Peak Throughput:** Single-carrier DECT NR+ (MCS 0) sustained **124.26 kbps** application goodput (**126.64 kbps** host arrival; **127.26 kbps** PHY on-air rate) at **62.4 packets/second** with maximum 249-byte frames and 100% packet delivery.
- **Relay Forwarding Consistency:** 2-hop cut-through forwarding demonstrated deterministic performance with sub-0.1 ms inter-arrival jitter standard deviation and zero forwarding queue drops.
- **Firmware & Logging Integrity:** The enhanced 32 KB ring buffer eliminated log drops entirely (`--- dropped ---` = 0), and direct synchronous shell execution prevented timeouts during rapid multi-packet bursts.

---

## 2. Experimental Setup & Methodology

### 2.1 Hardware Configuration
Three physical Conexio Stratus Pro dev kits were arranged in an indoor multi-hop topology:

| Node | Role | Device ID | Interface / Connection | Transmit Power Level | Notes |
|:---:|:---:|:---:|:---:|:---:|---|
| **Node A** | Source | `14402` | `socket://10.0.0.139:7777` | Level 10 (or 1) | Traffic generator; sweeps rate & size |
| **Node B** | Relay | `56992` | `socket://10.0.0.139:7778` | Level 3 | Cut-through router; dedup enabled |
| **Node C** | Sink | `44720` | `COM6` (local serial) | Level 10 | Network sink; microsecond logger |

> [!IMPORTANT]
> **Power Setting vs. RSSI Units:**  
> In the Conexio/Nordic DECT NR+ stack, the `power` setting (e.g. `exp sett power 10`, `power 3`, `power 1`) represents an **integer power level index (0 to 13)** corresponding to the 4-bit `transmit_power` field in the DECT NR+ Common PHY header (`phy_ctrl_field_common`). It is **NOT** a raw dBm value.  
> Conversely, **RSSI** is the received signal strength indicator measured at the receiver and is expressed in **dBm** (e.g. `-47.1 dBm`, `-67.9 dBm`).

```
[ Node A: Source ]  ----------------- Direct (hops=0, -47.1 dBm) ----------------->  [ Node C: Sink ]
        |                                                                                    ^
        +---> [ Node B: Relay (hops=1, -67.9 dBm) ] -----------------------------------------+
```

### 2.2 Telemetry & Time Base
Every transmission and reception event logs:
- `time_us`: On-board microsecond hardware uptime from `k_ticks_to_us_near64(k_uptime_ticks())`.
- `time`: On-board millisecond uptime from `k_uptime_get()`.
- `[HH:MM:SS.mmm]`: Host-side wall-clock timestamp recorded upon serial arrival at the PC.
- `seq`, `size`, `hops`, `rssi`: Protocol sequence number, payload size in bytes, hop count, and link RSSI in dBm.

### 2.3 Throughput & Cadence Calculation Methodology

#### Mathematical Formulation
Throughput is calculated per burst as:

$$\text{Throughput (kbps)} = \frac{N_{\text{delivered}} \times S_{\text{payload}} \times 8}{T_{\text{duration}} \times 1000}$$

Where:
- $N_{\text{delivered}}$ is the total number of packets delivered at the sink in the burst.
- $S_{\text{payload}}$ is the application payload size in bytes (18, 64, 128, or 249 bytes).
- $T_{\text{duration}}$ is the elapsed burst duration in seconds.

#### Hardware Ground Truth vs. Host UART Time
1. **On-Chip Hardware Timer ($T_{\text{hw}}$):** Measured between the first and last delivered packet of the burst using the sink node's hardware microsecond clock:
   $$T_{\text{hw}} = \frac{t_{\text{us, last}} - t_{\text{us, first}}}{1,000,000}$$
   This eliminates PC serial buffering, USB hub scheduling, and operating system latency, providing the true physical over-the-air arrival duration.
2. **Average Frame Cadence ($\Delta t_{\text{cadence}}$):** The average inter-packet transmission spacing across $N - 1$ intervals:
   $$\Delta t_{\text{cadence}} = \frac{T_{\text{hw}} \times 1000}{N_{\text{delivered}} - 1}\text{ ms}$$
3. **Application Goodput vs. PHY On-Air Rate:**
   - **Goodput:** Accounts strictly for application data payload bytes ($S_{\text{payload}}$).
   - **PHY Channel Rate:** Includes framing overhead (4-byte common PHY header, preamble, CRC, ~255 bytes total frame size). For the 249-byte payload burst at 10 ms nominal interval, Goodput is **124.26 kbps** while raw channel throughput is **127.26 kbps**.
   - **Host Arrival Rate:** Due to slight PC serial USB FIFO buffering at the end of the burst, host timestamps recorded a 1.57 s arrival span, yielding an apparent 126.64 kbps arrival rate on the PC interface.

---

## 3. Comprehensive Performance Summary

All metrics below are computed from the on-board microsecond hardware timer (`time_us`):

| Benchmark Experiment | Bursts Tested | Packets Sent | Packets Delivered | PDR (%) | Hardware Cadence | Packet Rate | Application Goodput |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **1-Hop vs. 2-Hop Latency** | 2 | 200 | 200 | **100.0%** | 506.1 ms | 2.0 pkt/s | 0.51 kbps |
| **Payload Scaling (18–249B)** | 4 | 400 | 400 | **100.0%** | 106.2 – 108.7 ms | 9.3 – 9.5 pkt/s | 1.37 – 18.51 kbps |
| **Rate Stress Sweep (500–10ms)** | 5 | 500 | 498 | **99.6%** | 16.5 – 511.5 ms | 2.0 – 61.1 pkt/s | 1.01 – 31.27 kbps |
| **Maximum Stress Throughput** | 3 | 300 | 300 | **100.0%** | 16.2 – 56.2 ms | 18.0 – 62.4 pkt/s | **35.81 – 124.26 kbps** |
| **Aggregate Test Suite** | **14** | **1,400** | **1,398** | **99.86%** | — | **Peak 62.4 pkt/s** | **Peak 124.26 kbps** |

---

## 4. Experiment 1: 1-Hop vs. 2-Hop Latency & Jitter Baseline

**Dataset:** `data/05_performance/1-Hop_vs._2-Hop_Latency_Baseline/`  
**Configuration:** 32-byte payload, nominal 500 ms interval, 100 packets per route.

### 4.1 Results & RF Distribution

| Route Path | Hop Header | Packets Delivered | PDR | Mean RSSI | Min RSSI | Max RSSI | Inter-Arrival StdDev |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Direct Path ($A \to C$)** | `hops=0` | 100 / 100 | **100.0%** | **-47.1 dBm** | -48.5 dBm | -46.5 dBm | 0.03 ms |
| **Relayed Path ($A \to B \to C$)** | `hops=1` | 100 / 100 | **100.0%** | **-67.9 dBm** | -69.5 dBm | -66.5 dBm | 0.05 ms |

### 4.2 Key Insights
1. **Deterministic Forwarding:** Node B logged exactly 100 `RX:` and 100 `FORWARD:` events without a single queue drop or retry.
2. **RF Path Discrimination:** The direct link showed high signal strength (-47.1 dBm) while the relayed link via Node B showed -67.9 dBm at the sink, confirming physical multipath separation.
3. **Arrival Jitter:** The inter-packet arrival jitter was negligible (standard deviation $< 0.05\text{ ms}$), demonstrating that the software cut-through pipeline introduces near-zero variance.

---

## 5. Experiment 2: Payload Scaling & Channel Efficiency

**Dataset:** `data/05_performance/Payload_Scaling___Maximum_Throughput/`  
**Configuration:** Fixed nominal interval (100 ms), sweeping frame payload size across 18, 64, 128, and 249 bytes (100 packets per burst).

### 5.1 Throughput Scaling Analysis

| Burst # | Payload Size | Sent | Delivered | Hardware Duration | Cadence ($\Delta t$) | Packet Rate | Goodput (Hardware) | Goodput (Host) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **18 Bytes** | 100 | 100 | 10.509 s | 106.15 ms | 9.5 pkt/s | **1.37 kbps** | 1.36 kbps |
| 2 | **64 Bytes** | 100 | 100 | 10.529 s | 106.36 ms | 9.5 pkt/s | **4.86 kbps** | 4.82 kbps |
| 3 | **128 Bytes** | 100 | 100 | 10.632 s | 107.40 ms | 9.4 pkt/s | **9.63 kbps** | 9.55 kbps |
| 4 | **249 Bytes** | 100 | 100 | 10.759 s | 108.68 ms | 9.3 pkt/s | **18.51 kbps** | 18.36 kbps |

### 5.2 Key Insights
- **Linear Scaling:** Throughput scales linearly with packet size ($1.37 \to 4.86 \to 9.63 \to 18.51\text{ kbps}$) at constant cadence (~106–108 ms).
- **MTU Integrity:** The 249-byte payload (the maximum standard single-frame payload for this physical layer configuration) operated without fragmentation overhead or packet loss.

---

## 6. Experiment 3: Rate Stress Sweep

**Dataset:** `data/05_performance/Rate_Stress_Sweep/`  
**Configuration:** Fixed 64-byte payload, progressively reducing interval: 500 ms, 200 ms, 50 ms, 20 ms, and 10 ms (100 packets per burst).

### 6.1 Rate Sweep Performance

| Burst # | Nominal Interval | Measured Cadence | Delivered | PDR | Hardware Duration | Packet Rate | Goodput |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 500 ms | 511.52 ms | 99 / 100 | 99.0% | 50.129 s | 2.0 pkt/s | 1.01 kbps |
| 2 | 200 ms | 206.37 ms | 100 / 100 | **100.0%** | 20.431 s | 4.9 pkt/s | 2.51 kbps |
| 3 | 50 ms | 56.37 ms | 100 / 100 | **100.0%** | 5.581 s | 17.9 pkt/s | 9.17 kbps |
| 4 | 20 ms | 26.38 ms | 100 / 100 | **100.0%** | 2.612 s | 38.3 pkt/s | 19.60 kbps |
| 5 | 10 ms | 16.54 ms | 99 / 100 | 99.0% | 1.621 s | **61.1 pkt/s** | **31.27 kbps** |

### 6.2 Key Insights
- **Queue Resilience:** Even at **61.1 packets/second** (16.5 ms actual physical spacing), only a single frame was dropped across the entire 100-packet burst.
- **Hardware FIFO Stability:** Across all 500 packets in this continuous stress test, total delivery reached **498 / 500 (99.6% PDR)**.

---

## 7. Experiment 4: Maximum Channel Capacity (Stress Throughput)

**Dataset:** `data/05_performance/Stress_Maximum_Throughput/`  
**Configuration:** Maximum payload (249 bytes) under aggressive transmission cadences (50 ms, 20 ms, 10 ms).

### 7.1 Peak Throughput Measurements

| Burst # | Nominal Interval | Measured Cadence | Packets Delivered | PDR | Hardware Duration | Packet Rate | Goodput (Hardware) | PHY Channel Rate |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | 50 ms | 56.19 ms | 100 / 100 | **100.0%** | 5.563 s | 18.0 pkt/s | **35.81 kbps** | 36.67 kbps |
| 2 | 20 ms | 26.19 ms | 100 / 100 | **100.0%** | 2.593 s | 38.6 pkt/s | **76.82 kbps** | 78.67 kbps |
| 3 | 10 ms | 16.19 ms | 100 / 100 | **100.0%** | 1.603 s | **62.4 pkt/s** | **124.26 kbps** | **127.26 kbps** |

### 7.2 Key Insights
- **Record Single-Carrier Goodput:** DECT NR+ sustained **124.26 kbps** application goodput (**127.26 kbps** PHY on-air throughput) with zero packet loss over 100 consecutive frames.
- **Modem Health:** Sustaining 62.4 packets/sec with 249-byte frames placed the radio at near-continuous transmit duty cycle; the nRF9151 modem coprocessor maintained 100% stability with zero modem reset events or error 24577.

---

## 8. System & Firmware Reliability Analysis

### 8.1 32 KB Serial Log Ring Buffer
In earlier builds with the default 4 KB buffer, high-rate bursts ($>30\text{ pkt/s}$) triggered kernel log drops (`--- dropped N messages ---`). 
With `CONFIG_LOG_BUFFER_SIZE=32768`:
- Zero log drops were observed across all 1,400 packets.
- Serial parser received 100% of formatted telemetry records verbatim.

### 8.2 Synchronous Command Execution
By updating the shell handler to emit responses synchronously via `shell_print` rather than queuing them through delayed log threads:
- Serial commands (`exp status`, `exp sett`) completed in $< 50\text{ ms}$.
- Desktop visualizer reported 0 connection timeouts across multi-hour testing.

---

## 9. Comparative Technology Positioning

| Technology Metric | DECT NR+ (Tested nRF9151) | LoRaWAN (EU/US) | Bluetooth Low Energy (1M) | Cellular NB-IoT |
|---|:---:|:---:|:---:|:---:|
| **Peak Goodput** | **124.26 kbps** | ~0.3 – 50 kbps | ~100 – 700 kbps | ~30 – 60 kbps |
| **Max Frame Payload** | **249 Bytes** | ~51 – 222 Bytes | 247 Bytes (ATT MTU) | Variable (IP) |
| **Max Burst Rate** | **62.4 pkt/s** | Heavy duty cycle ($1\%$) | ~50 – 100 pkt/s | Latency bound ($>1\text{ s}$) |
| **Topology** | Native Mesh / Multi-Hop | Star-only (Gateway) | Mesh / Star | Star (Tower) |
| **Licensing / Cost** | License-exempt 1.9 GHz | License-exempt ISM | License-exempt 2.4 GHz | Recurring SIM subscription |

---

## 10. Conclusion

Week 5 performance characterization validates the Conexio Stratus Pro DECT NR+ implementation as an enterprise-grade IoT wireless stack capable of combining multi-hop relaying with **124+ kbps** goodput and **99.86%** delivery reliability under heavy channel stress.
