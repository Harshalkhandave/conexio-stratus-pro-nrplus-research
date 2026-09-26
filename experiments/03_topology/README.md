# NR+ Topology Firmware (`03_topology`)

Three-node **application-layer** topology over DECT NR+ PHY (broadcast).  
Not Nordic FT/PT mesh routing — roles, forwarding, and neighbor state live in this app.

## What it does

| Role | Behavior |
|------|----------|
| **source** | Sends `DATA` to configured `dest_id`; listens; optional `HELLO` |
| **relay** | Listens; retransmits `DATA` (not for self) with `prev_hop` / `hop_count++` |
| **sink** | Listens; logs `DELIVER` when `dst` matches this node |

Shell controls **role** and **RF settings** at runtime (no rebuild for role swap).

## Build (nRF Connect UI)

Same flow as baseline: Board Root → `conexio_stratus_pro/nrf9151/ns` → sysbuild → region overlay.

| Fragment | Purpose |
|----------|---------|
| `overlay-us.conf` / `overlay-eu.conf` | **Required** carrier |
| *(default)* | Role starts as **source**; idle until `exp start` |

Optional Kconfig defaults: `CONFIG_TOPO_ROLE_RELAY`, `CONFIG_TOPO_ROLE_SINK`, `CONFIG_TOPO_DEST_ID`, `CONFIG_TOPO_DEVICE_ID_OVERRIDE`.

**Serial:** 115200 8N1.

## Shell (`exp`)

Boards boot **idle** by default (`TOPO_WAIT_FOR_START`), unless a **saved flash profile** has `autostart=on` (see persist below).

| Command | Meaning |
|---------|---------|
| `exp status` | Role, RF, counters, `autostart=` / `persist=` |
| `exp role source\|relay\|sink` | Set role (aliases: `src`, `router`, `gateway`) |
| `exp sett <key> <value>` | See keys below |
| `exp neigh` | Neighbor table (from HELLO/DATA RSSI) |
| `exp start` / `exp start 100` | Start run (source needs `dest`) |
| `exp stop` | Stop; radio prints `SUMMARY:` |
| `exp autostart on\|off` | Set auto-start flag in RAM |
| `exp save` | Persist role/RF/autostart to flash |
| `exp load` | Reload flash profile into RAM |
| `exp factory` | Erase flash profile; restore Kconfig defaults |

### `exp sett` keys

| Key | Range / notes |
|-----|----------------|
| `role` | `source` / `relay` / `sink` |
| `dest` | Destination device ID (required for source) |
| `interval` | ms between source DATA cycles |
| `hello` | ms between HELLOs (`0` = off) |
| `count` | Source DATA count (`0` = forever) |
| `power` | 0..13 |
| `mcs` | 0..7 |
| `size` | 18..32 |
| `max_hops` | 1..16 (relay drop if `hop_count >= max`) |
| `autostart` | `on`/`off` (same as `exp autostart`) |

Stop the run before changing settings. RAM changes need **`exp save`** to survive reset.

### Persist & autostart (Week 4)

Full guide: [`docs/03_topology/PERSIST_AUTOSTART.md`](../../docs/03_topology/PERSIST_AUTOSTART.md)

```text
exp role sink
exp sett hello 0
exp autostart on
exp save
# reset board → should auto-start as sink
```

## Quick three-board bring-up

1. Flash the same `03_topology` image (region overlay) on A, B, C.
2. Note each `device_id=` from boot log (or `exp status`).
3. Example (IDs illustrative):

```text
# Board A (source) — dest = C's id
exp role source
exp sett dest 0xC001
exp sett power 10
exp sett count 100

# Board B (relay)
exp role relay
exp sett max_hops 3

# Board C (sink)
exp role sink

# Then start sink/relay first, source last
# C: exp start
# B: exp start
# A: exp start
```

4. Look for `DELIVER:` on C (`hop=0` = direct, `hop>=1` = via relay) and `FORWARD:` on B.

## Packet (18 bytes)

`src`, `dst`, `prev_hop`, `message_type` (`DATA=1`, `HELLO=2`), `hop_count`, `flags`, `sequence`, `tx_time_ms`, XOR `checksum`.

`next_hop` is **not** on air — only in future local route tables.

## Log lines

```text
TX: node=… type=DATA|HELLO …
RX: node=… type=DATA|HELLO …
FORWARD_Q: / FORWARD: …
DELIVER: node=… seq=… src=… prev=… hops=… rssi=…
SUMMARY: role=… …
```

## Scope notes

- Application relay on PHY broadcast; report it that way.
- Duplicate / TTL limits reduce floods; not a full routing protocol yet.
- Neighbor table + HELLO are the base for later autonomous next-hop selection.
- Carrier stays in region overlays (not runtime).

## Report & visualizer

- How Exp 1–4 were run: [`docs/03_topology/PROCEDURE.md`](../../docs/03_topology/PROCEDURE.md)
- Persist / autostart after reset: [`docs/03_topology/PERSIST_AUTOSTART.md`](../../docs/03_topology/PERSIST_AUTOSTART.md)
- Characterization report: [`reports/03_topology/NR_Topology_Characterization_Report.md`](../../reports/03_topology/NR_Topology_Characterization_Report.md)
- Raw logs: `data/03_topology/`
- Visualizer plan: [`docs/03_topology/VISUALIZER_PLAN.md`](../../docs/03_topology/VISUALIZER_PLAN.md)
- **NR+ Network Visualizer v1.0:** [`tools/topology_visualizer/`](../../tools/topology_visualizer/) (`python app.py`)
