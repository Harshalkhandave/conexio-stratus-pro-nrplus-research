# Conexio Stratus Pro — DECT NR+ Research

Engineering workspace for characterizing **DECT NR+** on the [Conexio Stratus Pro](https://docs.conexiotech.com/) (nRF9151): RF behavior, reliability, topology, and product fit versus cellular / other IoT links.

| Item | Value |
|------|--------|
| Platform | Conexio Stratus Pro / nRF9151 (non-secure) |
| SDK | nRF Connect SDK **v3.2.1** |
| Board package | `conexio-firmware-sdk` (see Conexio docs) |

## Experiments & Firmware Roadmap

| Experiment | Focus Area | Key Features / Deliverables |
|---|---|---|
| **[`experiments/01_baseline/`](experiments/01_baseline/)** | **Baseline & Instrumentation** | Instrumented PHY baseline: sequenced packets, timestamps, structured `TX:`/`RX:` logging, runtime `exp` shell. |
| **[`experiments/02_range/`](experiments/02_range/)** | **Range & RF Characterization** | RF range & link characterization campaign with split-host automated test scripts. |
| **[`experiments/03_topology/`](experiments/03_topology/)** | **Multi-Hop Topology** | Three-node multi-hop forwarding ($A \to B \to C$), hop tracking, link metrics, and NVS flash profile persistence (`exp save`, autostart). |
| **[`experiments/04_healing/`](experiments/04_healing/)** | **Self-Healing & Failure Testing** | Fault tolerance, cold-boot recovery (~595 ms), severed relay healing, sink disconnection, and mobile relaying. |
| **[`experiments/05_performance/`](experiments/05_performance/)** | **Performance & Stress Characterization** | Baseline transit jitter, MTU payload scaling (18–249B), high-rate stress sweep (down to 10 ms), and channel throughput limit (124+ kbps goodput / 127 kbps PHY). |
| **[`experiments/06_store/`](experiments/06_store/)** | **Store-and-forward** | Hop custody, stop-and-wait ACK, and outage buffering. New image; `03_topology` stays the open-loop characterization firmware. |

---

## Desktop Visualization & Tools

- **[`tools/topology_visualizer/`](tools/topology_visualizer/)** — Real-time PyQt6 desktop topology visualizer with auto-discovery, interactive canvas, animated packet delivery, node inspector, live serial console, and NVS flash profile management.
- **[`tools/logger/`](tools/logger/)** — Python serial logger with local wall-clock timestamps, TCP serial redirection (`tcp_serial_redirect.py`), and the store-and-forward runner `sf_auto_test.py`.
- **[`tools/range_campaign/`](tools/range_campaign/)** — Automated multi-condition sweep harness (`range_campaign.py`, `range_tx.py`, `range_rx.py`).
- **[`tools/parser/`](tools/parser/)** — Serial log parser converting compact `TX:` / `RX:` feeds into tabular CSVs, plus multi-hop performance parser (`parse_performance.py`).

---

## Technical Reports

- **[`reports/03_topology/NR_Topology_Characterization_Report.md`](reports/03_topology/NR_Topology_Characterization_Report.md)** — Comprehensive characterization of three-node pairwise reachability, forwarding behavior, and path stability.
- **[`reports/04_healing/NR_Self_Healing_Report.md`](reports/04_healing/NR_Self_Healing_Report.md)** — Evaluation of fault recovery, cold-boot timelines, intermediate relay severance, and relay mobility ($40\text{ dBm}$ RSSI span).
- **[`reports/05_performance/NR_Performance_Report.md`](reports/05_performance/NR_Performance_Report.md)** — Multi-hop transit jitter, MTU payload scaling (18–249B), high-rate sweep resilience, and peak channel throughput (124.26 kbps goodput / 127.26 kbps PHY).
- **[`reports/06_store/NR_Store_and_Forward_Report.md`](reports/06_store/NR_Store_and_Forward_Report.md)** — Sink outage at 1 pkt/s: relay holds the backlog, refuses overflow without dropping it, and the sink delivers seq 0–887 in order (`size 16`).

---

## Build & flash (recommended)

Conexio recommends building with the **nRF Connect extension for VS Code**, not the CLI as the primary path.

Follow: [Compiling Applications with nRF Connect Extension for VS Code](https://docs.conexiotech.com/master/building-and-programming-an-application/compiling-applications-with-nrf-connect-extension-for-vs-code.md)

Summary:

1. Install NCS v3.2.1 and the [Conexio firmware SDK](https://docs.conexiotech.com/master/building-and-programming-an-application/fetch-conexio-firmware-sdk-and-board-definition-files.md) (including the MCUBoot patch).
2. In nRF Connect settings → **Board Roots**, add your `conexio-firmware-sdk` path (example on Windows: `C:\nordic\ncs\v3.2.1\conexio-firmware-sdk`).
3. **Open an existing application** → select `experiments/01_baseline` or `experiments/03_topology`.
4. **Add Build Configuration** → enable custom boards → select `conexio_stratus_pro/nrf9151/ns` → use **sysbuild**.
5. Add Extra Kconfig fragments as needed, e.g. `overlay-us.conf` or `overlay-eu.conf` (region), plus optional role overlays documented in the experiment README.
6. Build, put the device in **DFU mode**, flash with `newtmgr` / the flow in Conexio’s guide. Console: **115200 8N1**.

Full application details, overlays, and bring-up checks: [`experiments/01_baseline/README.md`](experiments/01_baseline/README.md) and [`experiments/03_topology/README.md`](experiments/03_topology/README.md).

---

## Repository Layout

```
conexio-stratus-pro-nrplus-research/
├── data/                    # Datasets (01_baseline, 02_range, 03_topology, 04_healing, 05_performance, 06_store)
├── docs/                    # Detailed architecture and procedures
│   ├── 01_baseline/         # Baseline bring-up, packet format, logging specs
│   ├── 03_topology/         # Multi-hop procedures, persistence, visualizer specs
│   ├── 04_healing/          # Self-healing and fault injection procedures
│   ├── 05_performance/      # Performance characterization & stress procedures
│   └── 06_store_and_forward/# Custody plan, procedure, and runbook
├── experiments/             # Zephyr / NCS firmware code
│   ├── 01_baseline/         # Baseline PHY application
│   ├── 02_range/            # Range campaign procedure
│   ├── 03_topology/         # Multi-hop & persistence firmware
│   ├── 04_healing/          # Self-healing experiment overview
│   ├── 05_performance/      # Performance, latency & throughput overview
│   └── 06_store/            # Hop-custody store-and-forward firmware
├── reports/                 # Formal engineering reports & evaluation
│   ├── 03_topology/         # Multi-hop topology characterization report
│   ├── 04_healing/          # Self-healing & recovery report
│   ├── 05_performance/      # Performance, latency & throughput report
│   └── 06_store/            # Store-and-forward outage report
└── tools/                   # Engineering tooling
    ├── logger/              # Serial logging & TCP redirects
    ├── parser/              # PDU & performance log parsers to CSV
    ├── range_campaign/      # Automated RF campaign runner
    └── topology_visualizer/ # PyQt6 Desktop visualizer application
```

## Regulatory Note

DECT NR+ uses regulated spectrum. Use the US/EU carrier overlays only where you are permitted to transmit, and follow local rules.
