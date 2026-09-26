# Week 4: Network Healing & Failure Testing Procedure

This document provides the standard experimental procedure for conducting and replicating **Week 4 Network Healing, Fault Injection, and Mobility** experiments on the Conexio Stratus Pro DECT NR+ platform.

---

## 1. Prerequisites & Equipment Setup

### Required Hardware
- **3x Conexio Stratus Pro** dev boards (nRF9151).
- **3x USB-C Cables** connected to the host PC (or to separate test hosts running `tools/logger/tcp_serial_redirect.py`).
- **Indoor Test Geometry:** Place Node A and Node C separated by at least 1–2 walls and ~15 meters. Setting Node A and Node C to `power 1` (minimum) ensures that direct $A \times C$ link is attenuated, forcing traffic through intermediate Node B (`power 3`).

### Firmware
All three nodes must be programmed with the `experiments/03_topology` firmware, which includes the application-layer forwarding pipeline and NVS flash persistence (`topo_persist.c`).

---

## 2. Setting Up the Nodes (Two Methods)

### Method A: Using the Topology Visualizer GUI (Recommended)

1. **Launch the Visualizer:**
   ```powershell
   cd tools/topology_visualizer
   .\.venv\Scripts\python.exe app.py
   ```
2. **Connect Boards:** In the **Connect** dialog, select the COM ports for all three boards (e.g., `COM7`, `COM8`, `COM9`) and click **Connect**.
3. **Rename Nodes:**
   - Double-click each node on the canvas (or press **F2**) and label them: `Node A`, `Node B`, and `Node C`.
   - Press **Ctrl+Shift+A** to arrange them automatically by role.
4. **Configure Node Parameters (Inspector → Settings Tab):**
   - **Node C (Sink):** Select Node C $\to$ Settings tab $\to$ set Role to `sink`, Power to `1`. Click **Apply** (amber button).
   - **Node B (Relay):** Select Node B $\to$ Settings tab $\to$ set Role to `relay`, Power to `3`. Click **Apply**.
   - **Node A (Source):** Select Node A $\to$ Settings tab $\to$ set Role to `source`, Destination to Node C's `device_id`, Power to `1`, Interval to `500 ms`. Click **Apply**.
5. **Persist Configuration to Flash (Inspector → Flash Tab):**
   - For each node (A, B, C):
     - Open the **Flash** tab.
     - Toggle **Auto-start on boot** to **ON**.
     - Click **Save Profile & Auto-start to Flash**.
     - Verify the bottom console outputs: `persist: saved profile to NVS`.

---

### Method B: Using Serial Shell Commands (`exp`)

Open serial terminals (115200 8N1) for each board and run:

1. **Node A (Source):**
   ```text
   exp stop
   exp sett role source
   exp sett dest <Node_C_ID>
   exp sett power 1
   exp sett interval 500
   exp autostart 1
   exp save
   ```
2. **Node B (Relay):**
   ```text
   exp stop
   exp sett role relay
   exp sett power 3
   exp autostart 1
   exp save
   ```
3. **Node C (Sink):**
   ```text
   exp stop
   exp sett role sink
   exp sett power 1
   exp autostart 1
   exp save
   ```

---

## 3. Experiment Procedures

---

### Test 1: Node A Cold Reboot (`Restart_A`)

#### Objective
Measure cold boot duration, NVS profile recovery, and latency to first packet delivery when the source node restarts.

#### Procedure via Visualizer
1. **Start Capture:** Click **Start capture** (or press **Ctrl+L**). Enter session name: `Restart_A`.
2. **Start Network:** Click **Start network** in the toolbar.
   - Verify steady state: Node A transmits, Node B forwards, and Node C delivers packets.
   - Amber packet circles animate along $A \to B \to C$ on the canvas.
3. **Trigger Reboot:** Press the physical **RESET** button on Node A (or unplug and reconnect its USB-C cable).
4. **Observe Visualizer Canvas:**
   - Node A card turns grey with an **Offline** badge.
   - Within $\sim 595\text{ ms}$, Node A boots, reloads its saved profile, and automatically enters RUNNING state.
   - The visualizer's auto-reconnect engine reconnects the port, restores Node A to **Online**, and green/amber packet animations resume automatically.
5. **Stop Capture:** Click **Stop capture** (Ctrl+L).
6. **Verify Data:** Check `tools/topology_visualizer/data/Restart_A/`:
   - `Node_A_log.txt`: Confirms `topo_persist: loaded profile` and `auto-start enabled` at $\sim 594\text{ ms}$.
   - `session.json` and `final_snapshot.json` report 100% PDR.

---

### Test 2: Intermediate Relay Reboot (`Restart_B`)

#### Objective
Observe interruption of forwarded traffic and autonomous route recovery when the relay reboots.

#### Procedure via Visualizer
1. **Start Capture:** Press **Ctrl+L** $\to$ enter `Restart_B`.
2. **Verify Active Relaying:** Ensure header displays `Path: relayed` and Node B's `fwd_sent` counter is incrementing.
3. **Trigger Reboot:** Press **RESET** on Node B while Node A is actively transmitting.
4. **Observe Visualizer Canvas:**
   - Node B transitions to **Offline**.
   - Animated packet delivery to Node C ceases (direct link $A \to C$ is absent due to `power 1`).
   - Node B reboots in $\sim 595\text{ ms}$, auto-starts its relay role from NVS, and reconnects in the visualizer.
   - On the very next packet received from Node A, amber packet animation to Node C resumes instantly.
5. **Stop Capture:** Press **Ctrl+L**.

---

### Test 3: Intermediate Relay Removal / Path Severance (`Remove_B`)

#### Objective
Demonstrate complete path loss and packet dropping when the sole intermediate relay is physically removed in an attenuated geometry.

#### Procedure via Visualizer
1. **Start Capture:** Press **Ctrl+L** $\to$ enter `Remove_B`.
2. **Sever Path:** Disconnect Node B's USB-C cable completely from the host PC / power source.
3. **Observe Visualizer Canvas:**
   - Node B card indicates **Offline (reconnecting...)**.
   - Directed link arrows ($A \to B$ and $B \to C$) disappear after the 3.0 s staleness timeout.
   - Direct link $A \to C$ remains absent (0 direct deliveries, `hops=0` count remains 0).
   - Node A continues transmitting (radio does not hang or error).
   - The header KPI **Delivery ratio** begins steadily declining from 100% downward.
4. **Duration:** Hold Node B offline for 30–60 seconds to observe sustained packet drops.

---

### Test 4: Intermediate Relay Restoration & Network Healing (`Restore_B`)

#### Objective
Demonstrate zero-touch self-healing upon relay power restoration.

#### Procedure via Visualizer
1. **Execution:** Directly follows Test 3 during the same active capture session (or as a fresh capture `Restore_B`).
2. **Restore Power:** Re-insert the USB-C cable into Node B.
3. **Observe Visualizer Canvas:**
   - The visualizer auto-reconnect engine detects Node B's COM port.
   - Node B boots in $\sim 595\text{ ms}$, loads `role=relay autostart=1` from flash, and immediately begins listening.
   - Canvas links $A \to B$ and $B \to C$ re-appear with live RSSI badges.
   - Amber animated packets resume flowing to Node C on the very next sequence.
4. **Stop Capture:** Press **Ctrl+L**.
5. **Snapshot Export:** Press **Ctrl+E** to export `final_snapshot.json`.

---

### Test 5: Destination Sink Disconnection (`Remove_C`)

#### Objective
Characterize source and relay behavior during gateway/sink downtime.

#### Procedure via Visualizer
1. **Start Capture:** Press **Ctrl+L** $\to$ enter `Remove_C`.
2. **Disconnect Sink:** Unplug Node C's USB cable while Node A and Node B are running.
3. **Observe Visualizer Canvas:**
   - Node C card turns grey (**Offline**).
   - Link $B \to C$ expires after 3 seconds.
   - Node A continues transmitting; Node B continues overhearing and logging `FORWARD` without unhandled errors (open-loop PHY broadcast).
4. **Reconnect Sink:** After 60 seconds, re-insert Node C.
5. **Observe Healing:** Node C auto-boots into `sink` role, reconnects in the visualizer, and resumes logging `DELIVER` events immediately.
6. **Stop Capture:** Press **Ctrl+L**.

---

### Test 6: Intermediate Relay Physical Mobility (`Move_B`)

#### Objective
Quantify link margin and PDR stability while physically moving Node B across varying RF path attenuation.

#### Procedure via Visualizer
1. **Start Capture:** Press **Ctrl+L** $\to$ enter `Move_B`.
2. **Setup:** Node A and Node C are powered from stationary host ports ~15 meters apart across walls. Node B is powered via a portable battery pack (or long cable / TCP redirect).
3. **Relocate Node B:**
   - **Position 1 (Near Sink):** Observe initial $B \to C$ link RSSI on the canvas (typically $-30$ to $-40\text{ dBm}$, color **green**).
   - **Position 2 (Transit Hallway):** Walk Node B into an adjacent hallway. Observe the link color shift to **lime** ($-50$ to $-65\text{ dBm}$).
   - **Position 3 (Furthest Point / Obstacle):** Walk to the furthest room. Observe link color shift to **amber** ($-70$ to $-77\text{ dBm}$).
   - **Position 4 (Corridor Openings):** If direct line-of-sight momentarily opens, observe temporary direct links (green packets) coexisting with relayed paths.
   - **Position 5 (Return):** Return Node B to the intermediate room.
4. **Observe Visualizer Canvas:**
   - Verify that **Delivery ratio** remains at **100%** throughout the entire relocation.
   - Live RSSI values on the link badges update dynamically with each received packet.
5. **Stop Capture:** Press **Ctrl+L**.

---

## 4. Post-Test Data Verification

After stopping capture in the visualizer, click the gear menu $\to$ **Open Data Folder** (or navigate to `tools/topology_visualizer/data/<name>/`):

1. **Verify Log Completeness:**
   - Ensure `Node_A_log.txt`, `Node_B_log.txt`, and `Node_C_log.txt` exist and contain wall-clock timestamps.
2. **Verify Manifest:** Open `session.json` and confirm all three nodes are documented with their `device_id` and assigned roles.
3. **Parse to CSV (Optional):**
   ```powershell
   python tools/parser/parse_tx_rx.py tools/topology_visualizer/data/Restart_A/Node_C_log.txt
   ```
4. **Archiving:** For benchmark runs intended for formal reporting, copy the session folder from `tools/topology_visualizer/data/<name>/` into `data/04_healing/<name>/`.
