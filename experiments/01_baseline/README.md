# NR+ Experimental Firmware — Baseline

DECT NR+ PHY application for **Conexio Stratus Pro** (nRF9151).  
Based on Nordic’s `hello_dect` sample, extended for repeatable lab measurements: binary PDUs, sequence numbers, timestamps, and machine-readable serial logs.

## Features

- Packed PDU with **sequence**, **TX timestamp**, and XOR **checksum**
- Structured logs: `TX:` / `RX:`
- Roles: **tx_rx** (default), **tx_only**, **rx_only**
- Kconfig options for interval, packet count, size, message type, optional device ID override

## Requirements

- nRF Connect SDK **v3.2.1**
- [Conexio firmware SDK & board files](https://docs.conexiotech.com/master/building-and-programming-an-application/fetch-conexio-firmware-sdk-and-board-definition-files.md) under your NCS tree (plus MCUBoot patch)
- DECT NR+ PHY modem firmware on the device
- At least two Stratus Pro boards on the same carrier and network ID
- Permission to operate on the DECT band in your region

## Build & program (recommended: nRF Connect UI)

Conexio’s **recommended** method is the nRF Connect extension (VS Code / Cursor), not west on the command line.

Guide: [Compiling Applications with nRF Connect Extension for VS Code](https://docs.conexiotech.com/master/building-and-programming-an-application/compiling-applications-with-nrf-connect-extension-for-vs-code.md)

| Step | Action |
|------|--------|
| 1 | Set **Board Roots** to your `conexio-firmware-sdk` directory |
| 2 | **Open existing application** → this folder (`experiments/01_baseline`) |
| 3 | **Add build configuration** → Custom boards → `conexio_stratus_pro/nrf9151/ns` |
| 4 | Enable **sysbuild** (Build system default / Use sysbuild) |
| 5 | Under Extra Kconfig fragments / Extra CMake arguments, add a region overlay (required): `overlay-us.conf` or `overlay-eu.conf` |
| 6 | Optionally add role overlays (see table below) |
| 7 | Build, enter **DFU mode**, upload `zephyr.signed.bin` with `newtmgr` as in the Conexio guide |

**Serial console:** 115200 8N1 (`uart0`).

### Region & role overlays

| File | Purpose |
|------|---------|
| `overlay-us.conf` | US carrier / TX power |
| `overlay-eu.conf` | EU carrier |
| *(none)* | Role **tx_rx** — transmit, then listen |
| `overlay-tx-only.conf` | Transmit only |
| `overlay-rx-only.conf` | Receive only |
| `overlay-1000pkts.conf` | Stop after 1000 transmissions |

In the UI, combine fragments as needed (region + role + packet count).

### Optional: west CLI

Only if you already use west regularly. Same board, `BOARD_ROOT`, and `EXTRA_CONF_FILE` as above. Prefer the UI for day-to-day Conexio builds.

## Configuration reference

Full tables: [configuration & bring-up](../../docs/01_baseline/BASELINE.md)

| Option | Default | Meaning |
|--------|---------|---------|
| `CONFIG_CARRIER` | overlay | RF channel (must be set) |
| `CONFIG_NETWORK_ID` | 91 | Network / short-ID filter |
| `CONFIG_MCS` | 0 | Modulation coding scheme |
| `CONFIG_TX_POWER` | 13 / overlay | TX power index |
| `CONFIG_TX_TRANSMISSIONS` | 0 | `0` = run until reset |
| `CONFIG_RX_PERIOD_S` | 5 | RX window (seconds) |
| `CONFIG_TX_INTERVAL_MS` | 500 | Pause between iterations |
| `CONFIG_EXPERIMENT_TEST_MODE_*` | TX_RX | Board role |
| `CONFIG_EXPERIMENT_PACKET_SIZE` | 15 | PDC size (15–32 bytes) |
| `CONFIG_EXPERIMENT_MESSAGE_TYPE` | 1 | `message_type` field |
| `CONFIG_EXPERIMENT_DEST_RECEIVER_ID` | 0 | `0` = broadcast |
| `CONFIG_EXPERIMENT_DEVICE_ID_OVERRIDE` | n | Optional fixed ID |
| `CONFIG_EXPERIMENT_LOG_COMPACT` | y | Prefer `TX:` / `RX:` lines |

## Packet format & logging

- [Packet format](../../docs/01_baseline/PACKET_FORMAT.md)
- [Logging & clock model](../../docs/01_baseline/LOGGING.md)

```text
TX: node=<id> seq=<n> size=<B> time=<tx_ms> type=<t>
RX: node=<id> seq=<n> from=<id> rssi=<d.d> time=<rx_ms> tx_time=<ms> size=<B> type=<t> cs=ok|fail
```

## Host tools

```text
cd tools/logger
python -m pip install -r requirements.txt
python serial_logger.py --list
python serial_logger.py COM9 --out ../../data/01_baseline/run1.txt
python ../parser/parse_tx_rx.py ../../data/01_baseline/run1.txt -o ../../data/01_baseline/run1.csv
```

## Board definition (device tree)

This application has no local board files. Hardware description comes from:

`…/conexio-firmware-sdk/boards/conexio/stratus_pro/`

(e.g. console on `uart0` @ 115200 in `conexio_stratus_pro_common.dtsi`).  
Board Roots / `BOARD_ROOT` must point at `conexio-firmware-sdk`.

## Bring-up check

1. Flash two boards with the same region overlay (default role `tx_rx`).
2. Open serial on both; confirm `device_id=…` and `TX:` / `RX:` lines.
3. Confirm `seq` increases and RX shows `cs=ok`.
