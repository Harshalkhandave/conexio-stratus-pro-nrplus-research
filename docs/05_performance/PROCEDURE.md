# Week 5: Performance, Latency & Throughput Characterization Procedure

This document provides the standard experimental procedure for conducting and replicating **Week 5 Performance Characterization, Payload Scaling, and High-Rate Stress** experiments on the Conexio Stratus Pro DECT NR+ testbed.

---

## 1. Prerequisites & Equipment Setup

### Required Hardware
- **3x Conexio Stratus Pro** dev kits (Nordic nRF9151).
- **USB-C Connections** or networked serial bridges:
  - Node A (Source): `socket://10.0.0.139:7777` (or local COM port)
  - Node B (Relay): `socket://10.0.0.139:7778` (or local COM port)
  - Node C (Sink): `COM6` (or local COM port)
- **Radio Antennas:** 1.9 GHz DECT NR+ compatible antennas properly torqued on each SMA connector.
- **RF Placement:**
  - Node A and Node C separated with moderate attenuation (~15–20 m or partition walls).
  - Node B positioned intermediately to provide clear multi-hop relay coverage.

### Firmware Requirements
All three nodes must be running `experiments/03_topology` compiled with:
- `CONFIG_LOG_BUFFER_SIZE=32768` (prevents serial buffer drops during bursts >60 pkt/s).
- Direct synchronous command output (`shell_print`) to avoid shell timeouts under heavy load.
- Maximum payload buffer sized for $\ge 249\text{ bytes}$ application payload.

---

## 2. Node Configuration

### Method A: Using the Topology Visualizer GUI (Recommended)

1. **Launch the Visualizer:**
   ```powershell
   cd tools/topology_visualizer
   .\.venv\Scripts\python.exe app.py
   ```
2. **Connect Boards:** Connect to all three nodes (`socket://10.0.0.139:7777`, `socket://10.0.0.139:7778`, `COM6`).
3. **Configure Roles:**
   - **Node C (Sink):** Role `sink`, `power 10`, `rx_win 2000`, `dedup 0`.
   - **Node B (Relay):** Role `relay`, `power 3`, `dedup 0`, `fwd cut_through`.
   - **Node A (Source):** Role `source`, Destination set to Node C's ID (`44720`), `power 10`.

> [!NOTE]
> The `power` parameter (e.g., `power 10`, `power 3`, `power 1`) represents an **integer power level index (0–13)** defined by the 4-bit `transmit_power` field in the DECT NR+ Common PHY header. It is **NOT** a raw dBm value. Received link quality is measured separately by the receiver as **RSSI in dBm**.


---

### Method B: Using Serial Shell Commands (`exp`)

Open terminal sessions (115200 8N1 or telnet/socket) to each node:

1. **Node C (Sink, ID 44720):**
   ```text
   exp stop
   exp sett role sink
   exp sett power 10
   exp sett rx_win 2000
   exp start
   ```

2. **Node B (Relay, ID 56992):**
   ```text
   exp stop
   exp sett role relay
   exp sett power 3
   exp sett fwd cut_through
   exp start
   ```

3. **Node A (Source, ID 14402):**
   ```text
   exp stop
   exp sett role source
   exp sett dest 44720
   exp sett power 10
   ```

---

## 3. Experimental Procedures

---

### Test 1: 1-Hop vs. 2-Hop Latency & Jitter Baseline

#### Objective
Establish clean baseline transit performance, measuring arrival jitter and RSSI delta between direct single-hop and intermediate relayed paths.

#### Execution Steps
1. **Start Capture Session:** In the visualizer, click **Start Capture** (Ctrl+L) with name `1-Hop_vs._2-Hop_Latency_Baseline`.
2. **Phase 1 (Direct 1-Hop):**
   - Node B stopped (`exp stop`).
   - Node A: `exp sett size 32`, `exp sett interval 500`, `exp sett count 100`.
   - Run `exp start` on Node A.
   - Wait for 100 packets to complete (`~50 seconds`).
3. **Phase 2 (Relayed 2-Hop):**
   - Node B started (`exp start`).
   - Node A transmit power adjusted to `power 1` (forcing relay through Node B at `power 3`).
   - Run `exp start` on Node A for another 100 packets.
4. **Stop Capture:** Click **Stop Capture** (Ctrl+L).
5. **Verify Data:** Check that `final_snapshot.json` reports 200 delivered packets with 100 direct (`hops=0`) and 100 relayed (`hops=1`).

---

### Test 2: Payload Scaling & Maximum Throughput

#### Objective
Evaluate throughput scaling and verify frame fragmentation / MAC layer handling across 18, 64, 128, and 249 byte payloads.

#### Execution Steps
1. **Start Capture Session:** Name: `Payload_Scaling___Maximum_Throughput`.
2. **Run Sweep Across Payload Sizes (100 packets per burst at 100 ms nominal interval):**
   - **18 Bytes:**
     ```text
     exp sett size 18
     exp sett interval 100
     exp sett count 100
     exp start
     ```
     Wait ~10.5 seconds for completion.
   - **64 Bytes:**
     ```text
     exp sett size 64
     exp start
     ```
     Wait ~10.5 seconds for completion.
   - **128 Bytes:**
     ```text
     exp sett size 128
     exp start
     ```
     Wait ~10.5 seconds for completion.
   - **249 Bytes (Max MTU):**
     ```text
     exp sett size 249
     exp start
     ```
     Wait ~10.5 seconds for completion.
3. **Stop Capture:** Click **Stop Capture**.
4. **Validation:** 400 total packets sent and delivered (100% PDR). Throughput scales from 1.40 kbps (18B) up to 18.89 kbps (249B).

---

### Test 3: Rate Stress Sweep

#### Objective
Sweep transmission interval down from 500 ms to 10 ms (at 64-byte payload) to test radio scheduler behavior, hardware FIFO buffers, and receiver queue stability under fast burst rates.

#### Execution Steps
1. **Start Capture Session:** Name: `Rate_Stress_Sweep`.
2. **Execute Five Successive Bursts (100 packets each, size=64):**
   - Burst 1 (500 ms): `exp sett interval 500` $\to$ `exp sett count 100` $\to$ `exp start`
   - Burst 2 (200 ms): `exp sett interval 200` $\to$ `exp sett count 100` $\to$ `exp start`
   - Burst 3 (50 ms): `exp sett interval 50` $\to$ `exp sett count 100` $\to$ `exp start`
   - Burst 4 (20 ms): `exp sett interval 20` $\to$ `exp sett count 100` $\to$ `exp start`
   - Burst 5 (10 ms): `exp sett interval 10` $\to$ `exp sett count 100` $\to$ `exp start`
3. **Stop Capture:** Click **Stop Capture**.
4. **Validation:** Sink log confirms at least 498 / 500 packets delivered ($\ge 99.6\%\text{ PDR}$) with maximum arrival rate exceeding 62 packets per second.

---

### Test 4: Stress Maximum Throughput

#### Objective
Evaluate the absolute channel throughput saturation limit on single-carrier DECT NR+ (MCS 0) by pairing maximum frame payload (249 bytes) with rapid intervals (50 ms, 20 ms, and 10 ms).

#### Execution Steps
1. **Start Capture Session:** Name: `Stress_Maximum_Throughput`.
2. **Configure Node A:**
   ```text
   exp sett size 249
   exp sett count 100
   ```
3. **Execute High-Throughput Bursts:**
   - **Burst 1 (50 ms interval):**
     `exp sett interval 50` $\to$ `exp start` (achieves ~36.5 kbps)
   - **Burst 2 (20 ms interval):**
     `exp sett interval 20` $\to$ `exp start` (achieves ~78.1 kbps)
   - **Burst 3 (10 ms interval):**
     `exp sett interval 10` $\to$ `exp start` (achieves **126.64 kbps**)
4. **Stop Capture:** Click **Stop Capture**.
5. **Validation:** 300 / 300 packets delivered (100% PDR). Peak throughput reaches **126.64 kbps** with zero radio lockups or modem crashes.

---

## 4. Post-Test Data Analysis

Run the automated performance parser to process the capture directory:

```powershell
python tools/parser/parse_performance.py data/05_performance -o reports/05_performance/summary.csv
```

Verify that:
1. `PDR` exceeds 99.5% across all runs.
2. `--- dropped ---` occurrences in `Node_*.log` files equal 0.
3. No modem error codes (`24577` or `-EIO`) appear in any node logs.
