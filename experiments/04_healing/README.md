# Week 4 — Network Healing & Failure Testing (`04_healing`)

This directory documents the experimental framework, configuration, and verification for **Week 4: Network Healing & Failure Testing** on the Conexio Stratus Pro (Nordic nRF9151) DECT NR+ platform.

---

## 1. Objective

Move beyond standard point-to-point power-cycling and intentionally break an active multi-hop network ($A \to B \to C$) to evaluate:
- Failure detection time and route degradation.
- Cold-boot and channel acquisition timelines.
- Autonomous network healing and zero-configuration rejoining.
- Performance impact during intermediate node severance and relocation.

---

## 2. Hardware Roles & Configuration

Three Conexio Stratus Pro physical devices are configured in a linear topology:

```
[ Node A: Source ]  ---(NR+ PHY)--->  [ Node B: Relay ]  ---(NR+ PHY)--->  [ Node C: Sink ]
  ID: 56992 (or 44720)                  ID: 14402                           ID: 44720 (or 56992)
  Power: 1 (minimum)                    Power: 3 (elevated)                 Power: 1 (minimum)
```

> [!NOTE]
> Setting Node A and Node C to `power 1` with spatial separation forces a strict multi-hop dependency where direct $A \times C$ transmission is physically attenuated. Node B acts as the necessary intermediate bridge.

---

## 3. Firmware Baseline

Week 4 experiments utilize the **`experiments/03_topology`** firmware, which incorporates:
- **Application-Layer Multi-Hop Forwarding:** `hops` header inspection and retransmission.
- **NVS Profile Persistence (`topo_persist.c`):** Automatically saves runtime role, destination ID, transmit power, and auto-start flag to Non-Volatile Storage.
- **Zero-Touch Auto-Start on Boot:** Boards boot directly into active operation in $\sim 595\text{ ms}$, enabling true self-healing without requiring manual serial shell interaction.

---

## 4. Test Suite Overview

| Experiment | Target Node | Action | Primary Metric |
|---|---|---|---|
| **Experiment 1** | Node A | Power cycle / reboot source | Cold boot time, time to first transmitted/delivered packet |
| **Experiment 2** | Node B | Power cycle / reboot relay | Route interruption duration, autonomous relay recovery |
| **Experiment 3** | Node B | Disconnect / remove relay | Complete route loss, packet dropping in strict multi-hop |
| **Experiment 4** | Node B | Reconnect / restore relay | Rejoining latency, zero-configuration path restoration |
| **Experiment 5** | Node C | Disconnect / remove sink | Upstream node behavior during destination outage |
| **Experiment 6** | Node B | Physically relocate relay | RSSI dynamic range ($-36.5$ to $-76.5\text{ dBm}$), link margin |

---

## 5. Artifacts & Documentation

- **Formal Report:** [`../../reports/04_healing/NR_Self_Healing_Report.md`](../../reports/04_healing/NR_Self_Healing_Report.md)
- **Step-by-Step Procedure:** [`../../docs/04_healing/PROCEDURE.md`](../../docs/04_healing/PROCEDURE.md)
- **Raw Datasets:** [`../../data/04_healing/`](../../data/04_healing/)
  - `Restart_A/` — Node A cold reboots
  - `Restart_B/` — Node B intermediate relay reboots
  - `Remove_B/` — Node B removal & severed route validation
  - `Remove_C/` — Gateway/Sink disconnection
  - `Move_B/` — Dynamic relay mobility during live transmission
- **Visualizer Tool:** [`../../tools/topology_visualizer/`](../../tools/topology_visualizer/)
