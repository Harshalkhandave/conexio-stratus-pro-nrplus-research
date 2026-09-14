# Week 3 topology — experiment procedure

How the four characterization experiments were run with `experiments/03_topology` and `tools/logger/serial_logger.py`.

**Results:** [`reports/03_topology/NR_Topology_Characterization_Report.md`](../../reports/03_topology/NR_Topology_Characterization_Report.md)  
**Logs:** `data/03_topology/`

---

## 1. Hardware and IDs (this campaign)

| Folder label | `device_id` | USB |
|--------------|-------------|-----|
| **A** | 56992 | COM on lab PC |
| **B** | 14402 | COM on lab PC |
| **C** | 44720 | COM on lab PC |

Same firmware image on all three (US carrier overlay `overlay-us.conf`, carrier 1711). Roles set at runtime via shell — no role overlays required.

---

## 2. Logging

On the PC that owns the COM ports (one logger per board):

```text
cd tools/logger
uv run serial_logger.py COMx --out ../../data/03_topology/<exp>/<name>.txt
```

- Interactive: type `exp …` in the logger window (same as a serial terminal).
- Host timestamps `[HH:MM:SS.mmm]` = that PC’s local clock.
- Close any other app using the same COM port first.
- Prefer one PC for all three ports so timestamps share one clock.

---

## 3. Shared prep (every board, every experiment)

```text
exp stop
exp sett hello 0
exp status          # confirm device_id and settings
```

Start order when multiple boards run: **sink → relay (if any) → source**.  
Stop order: **source → others**.

---

## 4. Experiment 1 — Direct connectivity

**Goal:** Pairwise A↔B, A↔C, B↔C (no relay).

### 1a — A → B

| Board | Commands |
|-------|----------|
| B | `exp role sink` → `exp start` |
| A | `exp role source` → `exp sett dest 14402` → `exp sett count 100` → `exp start` |
| C | stopped |

**Logs:** `data/03_topology/exp_1/A-B/exp_A.txt`, `exp_B.txt`  
**Expect:** B `DELIVER` ×100; A `SUMMARY … data_sent=100`.

### 1b — A → C

| Board | Commands |
|-------|----------|
| C | `exp role sink` → `exp start` |
| A | `exp role source` → `exp sett dest 44720` → `exp sett count 100` → `exp start` |
| B | stopped |

**Logs:** `exp_1/A-C/`

### 1c — B → C

| Board | Commands |
|-------|----------|
| C | `exp role sink` → `exp start` |
| B | `exp role source` → `exp sett dest 44720` → `exp sett count 100` → `exp start` |
| A | stopped |

**Logs:** `exp_1/B-C/`

---

## 5. Experiment 2 — Three-node path A → B → C

**Goal:** Prove application relay (B forwards; C may see hops=0 and hops=1).

| Order | Board | Commands |
|-------|--------|----------|
| 1 | C | `exp role sink` → `exp start` |
| 2 | B | `exp role relay` → `exp sett max_hops 3` → `exp start` |
| 3 | A | `exp role source` → `exp sett dest 44720` → `exp sett count 100` → `exp sett power 7` → `exp start` |

**Logs:** `data/03_topology/exp_2/exp_{A,B,C}.txt`  
**Expect:** B `FORWARD` / `fwd_sent=100`; C `DELIVER` with mix of `hops=0` and `hops=1`.

---

## 6. Experiment 3 — Move B

**Goal:** Observe path / RSSI behavior when the intermediate node moves.

1. Same roles as Exp 2 (C sink, B relay, A source).
2. A: `exp sett dest 44720`, optional `exp sett count 0` (forever) or ~100+.
3. Start C → B → A.
4. Relocate B during the run (or between short stop/start slices).
5. Stop and save logs.

**Logs:** `data/03_topology/exp_3/`  
**Expect:** B still forwards; C still delivers; RSSI range may widen.

---

## 7. Experiment 4 — Weak direct A–C; B useful

**Goal:** Geometry/power such that A barely/does not reach C directly; B still relays.

| Order | Board | Commands |
|-------|--------|----------|
| 1 | C | `exp role sink` → `exp start` |
| 2 | B | `exp role relay` → `exp sett max_hops 3` → `exp start` |
| 3 | A | `exp role source` → `exp sett dest 44720` → `exp sett power 1` → `exp sett count 100` → `exp start` |

**Logs:** `data/03_topology/exp_4/`  
**Expect (this campaign):** C `DELIVER` only with **`hops=1`**; B `fwd_sent=100`.

Optional control: stop B and repeat — C should get few/no delivers (not required if Exp 4 already shows hops=0 count = 0).

---

## 8. What “implemented” means in firmware

Not a separate binary per experiment. One app (`03_topology`) implements:

| Mechanism | Implementation |
|-----------|----------------|
| Roles | Shell `exp role` / runtime (`source` / `relay` / `sink`) |
| Forwarding | Relay RX path → `FORWARD_Q` → `FORWARD` with `prev_hop`, `hop++` |
| Delivery | Sink (or any node) when `dst == me` → `DELIVER` |
| RF knobs | `exp sett power\|interval\|count\|max_hops\|…` |
| Dup / TTL | Seen table + `max_hops` |

Experiments differ by **placement**, **roles**, and **settings**, not by different firmware trees.

---

## 9. Checklist after each run

1. Source prints `SUMMARY` (`count_reached` or `stop`).
2. Capture sink/relay `SUMMARY` after `exp stop`.
3. Confirm log files under the correct `data/03_topology/exp_*` folder.
4. Note establishment: host time of A `>>> exp start` vs first C `DELIVER`.
