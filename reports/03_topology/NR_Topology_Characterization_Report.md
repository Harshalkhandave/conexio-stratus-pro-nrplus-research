# NR+ Topology Characterization Report

**Project:** Conexio Stratus Pro — DECT NR+ evaluation  
**Firmware:** `experiments/03_topology` (application-layer topology on DECT NR+ PHY)  
**SDK:** nRF Connect SDK v3.2.1  
**Data:** `data/03_topology/`  
**Date of measurements:** 2026-09-13  

---

## 1. Scope and method

### 1.1 Objective

Characterize three-node behavior: pairwise connectivity, packet forwarding on an intermediate node, hop count, link quality, path stability when the relay moves, and usefulness of the relay when the direct source–sink link is weak.

### 1.2 Important limitation (stack)

Nordic’s current PHY-oriented samples do not provide DECT NR+ mesh routing. This work uses **application-layer roles** over **PHY broadcast**:

| Role | Behavior |
|------|----------|
| **source** | Originate `DATA` to a configured `dest_id` |
| **relay** | Retransmit overheard `DATA` not addressed to self (`prev_hop`, `hop_count++`) |
| **sink** | Accept `DATA` when `dst` matches; log `DELIVER` |

**Parent / next-hop** in this report means the **configured** relay role (node B), not autonomous FT/PT or DLC routing. Path taken is observed from `prev_hop` and `hop_count` in logs.

### 1.3 Nodes (as labeled in data folders)

| Label | `device_id` | Typical role |
|-------|-------------|--------------|
| **A** | 56992 | source |
| **B** | 14402 | sink (Exp 1) / relay (Exp 2–4) |
| **C** | 44720 | sink |

Carrier **1711** (US overlay), network ID `0x5b`, hello disabled (`exp sett hello 0`), packet size 18 bytes.

### 1.4 Timing

Host timestamps `[HH:MM:SS.mmm]` come from the PC running `tools/logger/serial_logger.py` (local wall clock). Board `time=` fields are per-node uptime and are **not** used for cross-node delay.

**Route establishment time** = host time of source `>>> exp start` → host time of first sink `DELIVER:`.

---

## 2. Experiment 1 — Direct connectivity

**Goal:** Pairwise reachability and link quality without a relay.

| Link | Source → sink | Sent | Delivered | PDR | Sink RSSI (min / avg / max) |
|------|---------------|------|-----------|-----|------------------------------|
| A–B | 56992 → 14402 | 100 | 100 | **100%** | −39.0 / −33.0 / −31.0 dBm |
| A–C | 56992 → 44720 | 100 | 100 | **100%** | −48.0 / −40.0 / −37.5 dBm |
| B–C | 14402 → 44720 | 100 | 100 | **100%** | −19.5 / −17.5 / −17.0 dBm |

**Establishment (host):** ≈ **1.2 s** on each pair (first `DELIVER` after source `exp start`).

**Finding:** All three pairwise links are reliable at the test geometry. B–C is the strongest (highest RSSI).

---

## 3. Experiment 2 — Three-node path (A → B → C)

**Setup:** C sink → B relay (`max_hops=3`) → A source (`dest=44720`, count 100, power 7).

| Node | Role | Key counters |
|------|------|----------------|
| A | source | `data_sent=100` |
| B | relay | `rx_ok=100`, **`fwd_sent=100`** |
| C | sink | **`deliver=200`** |

**Hop breakdown at C**

| Path | Count | Evidence |
|------|-------|----------|
| Direct (hops=0) | 100 | `DELIVER … hops=0` (typically `prev=56992`) |
| Via B (hops=1) | 100 | `DELIVER … hops=1` (`prev=14402`) |

B logged matching `FORWARD_Q` / `FORWARD` for seq 0…99.

**Establishment:** ≈ **1.23 s** (18:05:36.038 → 18:05:37.272).

**Finding:** Forwarding works. On PHY broadcast, when A still reaches C, the sink correctly sees **both** direct and relayed copies (200 delivers for 100 sequences).

---

## 4. Experiment 3 — Physical separation / move B

**Setup:** Same roles as Exp 2; B relocated during / for the run (count ~102).

| Node | Counters | Notes |
|------|----------|--------|
| A | `data_sent=102` | |
| B | **`fwd_sent=102`** | Relay RSSI to A spanned ≈ −67.5 … −38.0 dBm |
| C | **`deliver=203`** | ≈ **101× hops=0** + **102× hops=1**; RSSI min **−76.5** dBm |

**Establishment:** ≈ **1.24 s**.

**Finding:** After moving B, the relay path remained active (full forward count). Direct and relayed paths still coexisted. Wider RSSI range at C is consistent with geometry change (**route / path observation** via hop mix and RSSI, not an autonomous routing table update).

---

## 5. Experiment 4 — Poor direct A–C; B as useful intermediate

**Setup:** A at **power 1**, B relay, C sink, count 100.

| Node | Counters | Notes |
|------|----------|--------|
| A | `data_sent=100`, power 1 | |
| B | **`fwd_sent=100`**, `rx_ok=100` | Heard A at ≈ **−72 / −71.5 / −71** dBm |
| C | **`deliver=100`** | **100× hops=1**, **0× hops=0** |

**Establishment:** ≈ **2.54 s** (18:35:34.464 → 18:35:37.007) — longer than Exp 2; consistent with delivery only after the relay hop.

**Finding:** Direct A→C did not produce hop-0 delivers. End-to-end delivery was **entirely via B**. This demonstrates that the intermediate node provides a **useful multi-hop path** when the direct link is ineffective.

---

## 6. Mapping to plan metrics

| Plan item | How measured | Result |
|-----------|--------------|--------|
| **Parent / next-hop** | Configured: B = relay for A→C traffic | Documented; observed `prev=14402` on hop-1 delivers |
| **Route establishment time** | Host Δ(t_start → first DELIVER) | ≈ 1.2 s (Exp 1–3); ≈ 2.5 s (Exp 4, relay-only) |
| **Route changes** | Hop mix / path in use | Exp 2–3: dual path; Exp 4: relay-only |
| **Hop count** | `hops=` / `hop=` in logs | 0 (direct), 1 (via B) |
| **Link quality** | RSSI + PDR | Exp 1: 100% PDR; Exp 4: weak A–B RSSI but 100% forward→deliver |
| **Packet forwarding** | `FORWARD` / `fwd_sent` | 100% of heard DATA forwarded in Exp 2–4 |
| **Route stability** | Sustained delivers + forward counts | Stable over 100+ packets; Exp 3 survived B move |

---

## 7. Conclusions

1. Three Stratus Pro boards form a reliable **PHY broadcast** neighborhood at the tested range (Exp 1).  
2. Application **relay** correctly increments hop count and rewrites `prev_hop`; the sink logs both direct and forwarded deliveries when both links work (Exp 2–3).  
3. When direct A–C is suppressed (low TX power / geometry), **B alone completes the path** (Exp 4) — the core multi-hop value demonstration.  
4. This is **not** Nordic FT/PT mesh routing; report claims stay at **application relay on NR+ PHY**.

---

## 8. Data index

```text
data/03_topology/
  exp_1/A-B/   exp_A.txt, exp_B.txt
  exp_1/A-C/   exp_A.txt, exp_C.txt
  exp_1/B-C/   exp_B.txt, exp_C.txt
  exp_2/       exp_A.txt, exp_B.txt, exp_C.txt
  exp_3/       exp_A.txt, exp_B.txt, exp_C.txt
  exp_4/       exp_A.txt, exp_B.txt, exp_C.txt
```

**How experiments were run (step-by-step shell + logging):**  
[`docs/03_topology/PROCEDURE.md`](../../docs/03_topology/PROCEDURE.md)

Firmware: `experiments/03_topology/`  
Logger: `tools/logger/serial_logger.py`
