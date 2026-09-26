# Topology Visualizer Capture Data (`tools/topology_visualizer/data`)

This directory stores session captures recorded by the **NR+ Network Visualizer** (`tools/topology_visualizer/app.py`).

---

## 1. Directory Structure

When an operator clicks **Start capture** (or presses **Ctrl+L**) and enters a session name (e.g., `Restart_A`, `Remove_B`, `Move_B`), a new directory is created:

```text
tools/topology_visualizer/data/
└── <session_name>/
    ├── <node_name>_log.txt      # e.g., Node_A_log.txt
    ├── <node_name>_log.txt      # e.g., Node_B_log.txt
    ├── <node_name>_log.txt      # e.g., Node_C_log.txt
    ├── session.json             # Capture metadata & participating nodes
    └── final_snapshot.json      # Final network graph, counters, and KPIs
```

---

## 2. Output File Specifications

### A. Per-Node Serial Logs (`<node_name>_log.txt`)
- **Format:** Plain text, UTF-8.
- **Naming Rule:** Derived from the display name set on the canvas (e.g. `Node_A_log.txt`, `Node_B_log.txt`).  
  *(Note: The `_log` suffix is intentional; on Windows, filenames like `COM9.txt` are reserved system device names that cause file locking and OneDrive synchronization failures).*
- **Timestamps:** Every line is prepended with the host PC's wall-clock timestamp:
  ```text
  [18:19:04.123] TX: node=44720 seq=0 size=18 time=12400
  [18:19:04.145] RX: node=14402 seq=0 from=44720 rssi=-42.0 time=12422
  [18:19:04.150] FORWARD: seq=0 prev=44720 hops=1
  [18:19:04.172] DELIVER: node=56992 seq=0 src=44720 prev=14402 hops=1 rssi=-36.5
  ```
- **Sanitization:** Stripped of ANSI terminal color escapes (`\x1b[...m`) and bare prompt characters (`uart:~$ `) to ensure clean ingestion by automated parsers.
- **Compatibility:** Fully compatible with `tools/parser/parse_tx_rx.py` and Python pandas/matplotlib processing pipelines.

---

### B. Session Manifest (`session.json`)
Written immediately upon starting capture and finalized on stop:

```json
{
  "app_version": "0.1.0",
  "session_name": "Remove_B",
  "started_at": "2026-09-25T18:19:04.100Z",
  "stopped_at": "2026-09-25T18:21:25.850Z",
  "line_count": 842,
  "nodes": {
    "COM7": {
      "display_name": "Node A",
      "device_id": 44720,
      "role": "source",
      "log_file": "Node_A_log.txt"
    },
    "COM8": {
      "display_name": "Node B",
      "device_id": 14402,
      "role": "relay",
      "log_file": "Node_B_log.txt"
    },
    "COM9": {
      "display_name": "Node C",
      "device_id": 56992,
      "role": "sink",
      "log_file": "Node_C_log.txt"
    }
  }
}
```

---

### C. Network Snapshot (`final_snapshot.json`)
Automatically generated when capture stops (or exported on demand via **Ctrl+E**). Captures the state of the entire network graph, per-node telemetry, and aggregate KPIs:

```json
{
  "timestamp": "2026-09-25T18:21:25.850Z",
  "kpis": {
    "nodes_online": 3,
    "nodes_running": 3,
    "path_class": "relayed",
    "delivery_ratio": 100.0,
    "route_setup_s": 1.24,
    "route_changes": 10,
    "mean_rssi_dbm": -41.2
  },
  "nodes": [
    {
      "name": "Node A",
      "device_id": 44720,
      "role": "source",
      "status": "running",
      "dest": 56992,
      "power": 1,
      "interval_ms": 500,
      "tx_sent": 49,
      "rx_ok": 0,
      "deliver": 0,
      "fwd_sent": 0,
      "last_rssi": null
    },
    {
      "name": "Node B",
      "device_id": 14402,
      "role": "relay",
      "status": "running",
      "dest": 0,
      "power": 3,
      "interval_ms": 500,
      "tx_sent": 0,
      "rx_ok": 28,
      "deliver": 0,
      "fwd_sent": 28,
      "last_rssi": -42.0
    },
    {
      "name": "Node C",
      "device_id": 56992,
      "role": "sink",
      "status": "running",
      "dest": 0,
      "power": 1,
      "interval_ms": 500,
      "tx_sent": 0,
      "rx_ok": 28,
      "deliver": 28,
      "fwd_sent": 0,
      "last_rssi": -36.5
    }
  ],
  "links": [
    {
      "source_id": 44720,
      "dest_id": 14402,
      "rssi_dbm": -42.0,
      "quality": "good",
      "packet_count": 28,
      "last_seen_s": 0.4
    },
    {
      "source_id": 14402,
      "dest_id": 56992,
      "rssi_dbm": -36.5,
      "quality": "excellent",
      "packet_count": 28,
      "last_seen_s": 0.4
    }
  ]
}
```

---

## 3. Relationship to `data/04_healing/`

- **`tools/topology_visualizer/data/`**: Working capture directory where the visualizer writes by default during active test runs.
- **`data/04_healing/`**: The formal repository archive where validated experimental datasets referenced in reports (`reports/04_healing/NR_Self_Healing_Report.md`) are permanently curated.
