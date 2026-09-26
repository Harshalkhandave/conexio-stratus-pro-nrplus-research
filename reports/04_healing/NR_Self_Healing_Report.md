# NR+ Self-Healing & Failure Recovery Report

**Project:** Conexio Stratus Pro — DECT NR+ evaluation  
**Firmware:** `experiments/03_topology` (with NVS Flash Persistence & Auto-Start)  
**SDK:** nRF Connect SDK v3.2.1  
**Data:** `data/04_healing/`  
**Date of measurements:** 2026-09-25  

---

## 1. Scope and method

### 1.1 Objective
Characterize fault recovery, cold-boot latency, route degradation under relay removal, autonomous healing via NVS flash persistence, sink downtime, and link stability under relay mobility in a three-node network ($A \to B \to C$).

### 1.2 Multi-hop geometry & role setup
Setting Node A (source) and Node C (sink) to **power 1** across 1–2 walls suppresses the direct $A \leftrightarrow C$ link, forcing all traffic through intermediate Node B (**power 3**).

| Label | `device_id` | Role | Power | Role in tests |
|---|---|---|---|---|
| **A** | 44720 (or 56992) | source | 1 | Traffic generator (`interval=500 ms`) |
| **B** | 14402 | relay | 3 | Intermediate relay (fault injection target) |
| **C** | 56992 (or 44720) | sink | 1 | Target sink / delivery logger |

### 1.3 Timing & recovery definitions
- **Cold Boot Time:** Time from reset assertion to kernel ready and NVS profile loaded.
- **First Packet Time:** Host time of node boot $\to$ host time of first sink `DELIVER:`.
- **Healing Time:** Duration from hardware power-on until active forwarding resumes.

---

## 2. Summary of failure events & recovery metrics

| Event | Fault Trigger | Detection Time | Healing / Recovery Time | First Packet Post-Recovery | Failed Trials | PDR (while online) |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **Restart A** | Cold reset on source | N/A (originator) | **595 ms** | **1.09 s** (`seq 0` at sink) | 0 / 20 | **100.0%** |
| **Restart B** | Cold reset on relay | 1 packet cycle | **595 ms** + **< 500 ms** (rx) | First arriving sequence | 0 / 10 | **100.0%** |
| **Remove B** | Unplug relay power | 1 packet cycle | Path severed ($A \times C$) | None until B restored | 0 | **0.0%** (outage) |
| **Restore B** | Re-power relay | **< 20 ms** (first RX) | **595 ms** from power-on | Immediate forwarding (`fwd=100%`) | 0 / 10 | **100.0%** |
| **Remove C** | Unplug sink | N/A (open broadcast) | Immediate upon C boot | First sequence after boot | 0 | **100.0%** (post-reconnect) |
| **Move B** | Relocate relay (40 dBm span) | Live monitoring | **0 ms** (continuous) | Continuous delivery | 0 | **100.0%** (40 / 40) |

---

## 3. Experiment 1 — Source cold reboot (`Restart_A`)

**Setup:** Node A reset repeatedly via hardware button; B relay; C sink.

| Node | Role | Key counters / measurements |
|---|---|---|
| **A** | source | Boot to NVS restore: **595 ms**; `data_sent` resumed cleanly |
| **B** | relay | `fwd_sent` tracks source transmissions without stall |
| **C** | sink | First delivery at **1.09 s** after source boot (`hops=1`) |

**Establishment:** ≈ **1.09 s** from power-on to sink delivery.  
**Finding:** Node A loads its saved profile (`role=source dest=C autostart=1`) and resumes transmission at `seq 0` within 595 ms. PDR is 100% post-boot.

---

## 4. Experiment 2 & 3 — Relay reboot & removal (`Restart_B` & `Remove_B`)

**Setup:** Node B rebooted and held offline across multiple cycles; Node A transmitting at `power 1`.

| Node | Role | Key counters | Notes |
|---|---|---|---|
| **A** | source | `data_sent=49`, power 1 | Continues transmitting without hardware hang |
| **B** | relay | `rx_ok=28`, **`fwd_sent=28`** | 100% forwarding success while online |
| **C** | sink | **`deliver=28`** | **28× hops=1**, **0× hops=0** |

**Hop breakdown at C:**
- **Relayed via B (`hops=1`):** 28 packets
- **Direct (`hops=0`):** 0 packets (strict relay dependency verified)

**Finding:** Because direct $A \times C$ link is suppressed, packet delivery ceases entirely while Node B is offline. Once Node B is awake, forwarding is 100% reliable with 0 duplicate or corrupt frames.

---

## 5. Experiment 4 — Relay restoration (`Restore_B`)

**Setup:** Re-connecting Node B after removal.

| Phase | Observed behavior |
|---|---|
| **Power ON $\to$ Boot** | Zephyr kernel ready & NVS profile loaded in **595 ms** |
| **Channel Entry** | Overhears Node A within **< 20 ms** of radio bringup |
| **Forwarding** | Immediately logs `FORWARD_Q` and `FORWARD` on the very first incoming packet |
| **Sink Delivery** | Node C logs `DELIVER … hops=1` without requiring manual reconnect commands |

**Finding:** True zero-touch network healing achieved via NVS flash persistence. Rejoining and route restoration require zero human intervention.

---

## 6. Experiment 5 — Sink disconnection (`Remove_C`)

**Setup:** Node C disconnected for 65 seconds while Node A and B remain active.

| Node | Role | Behavior during outage | Behavior after reconnect |
|---|---|---|---|
| **A** | source | Continues periodic transmission (no ACK backpressure) | Seamless continuation |
| **B** | relay | Continues overhearing and forwarding | Seamless continuation |
| **C** | sink | Offline (15 unacknowledged frames during outage) | Immediately resumes `DELIVER` upon boot |

**Finding:** DECT NR+ PHY broadcast operates open-loop. Upstream nodes continue normal transmission without crashing or stalling.

---

## 7. Experiment 6 — Relay mobility (`Move_B`)

**Setup:** Node B relocated across multiple rooms and hallways during active 40-packet transmission.

| Location phase | Sequence range | Observed Sink RSSI | Delivery status |
|---|---|---|---|
| **Near Sink** | `seq 0–10` | −36.5 dBm (strong) | 100% delivered (`hops=1`) |
| **Hallway Transit** | `seq 11–18` | −51.5 dBm | 100% delivered (`hops=1`) |
| **Obstacle Boundary** | `seq 19–28` | −76.5 dBm (weak) | 100% delivered (2× direct `hops=0` in open corridor) |
| **Return Transit** | `seq 29–39` | −48.0 … −42.0 dBm | 100% delivered (`hops=1`) |

**Finding:** The intermediate link dynamically adapted across a **40.0 dBm RSSI swing** with **100% PDR (40 of 40 sequences delivered)** and zero FCS/CRC errors.

---

## 8. Conclusions

1. **Deterministic Fast Boot:** NVS-backed persistence restores node roles and RF state in **$595\text{ ms}$**, enabling rapid autonomous healing without manual configuration.
2. **Relay Necessity & Zero-Touch Restoration:** When direct paths are blocked, intermediate relays provide an indispensable bridge. Restoration is instantaneous upon relay channel listening.
3. **Open-Loop Broadcast Limitation:** During sink outages, upstream nodes continue transmitting transparently. Mission-critical telemetry will benefit from store-and-forward buffering.
4. **RF Link Margin Headroom:** Even at −76.5 dBm during dynamic physical movement, the nRF9151 radio maintained 100% packet delivery without degradation.

---

## 9. Data index

```text
data/04_healing/
  Restart_A/   Node_A_log.txt, Node_B_log.txt, Node_C_log.txt, session.json, final_snapshot.json
  Restart_B/   Node_A_log.txt, Node_B_log.txt, Node_C_log.txt, session.json, final_snapshot.json
  Remove_B/    Node_A_log.txt, Node_B_log.txt, Node_C_log.txt, session.json, final_snapshot.json
  Remove_C/    Node_A_log.txt, Node_B_log.txt, Node_C_log.txt, session.json, final_snapshot.json
  Move_B/      Node_A_log.txt, Node_B_log.txt, Node_C_log.txt, session.json, final_snapshot.json
```

**Step-by-step procedures:**  
[`docs/04_healing/PROCEDURE.md`](../../docs/04_healing/PROCEDURE.md)

Firmware: `experiments/03_topology/`  
Console & Visualizer: `tools/topology_visualizer/`
