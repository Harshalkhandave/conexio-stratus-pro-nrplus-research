# Baseline firmware reference (`01_baseline`)

Application path: `experiments/01_baseline/`  
Platform: Conexio Stratus Pro / nRF9151 (non-secure)  
SDK: nRF Connect SDK v3.2.1

## Operating modes

Role is selected at build time (Kconfig / overlay):

| Mode | Behavior |
|------|----------|
| `tx_rx` (default) | Transmit one packet → receive for `CONFIG_RX_PERIOD_S` → sleep `TX_INTERVAL_MS` |
| `tx_only` | Transmit → sleep `TX_INTERVAL_MS` |
| `rx_only` | Repeated receive windows only |

For link measurements (PDR, range), prefer asymmetric roles: one node `tx_only`, one node `rx_only`, same carrier and network ID. Identical `tx_rx` schedules on both nodes can phase-align after a simultaneous reset and miss each other’s transmissions.

## Build and programming

Preferred method: nRF Connect for VS Code / Cursor, as described in the [Conexio documentation](https://docs.conexiotech.com/master/building-and-programming-an-application/compiling-applications-with-nrf-connect-extension-for-vs-code.md).

- Board target: `conexio_stratus_pro/nrf9151/ns`
- Board root: `conexio-firmware-sdk` (example: `C:/nordic/ncs/v3.2.1/conexio-firmware-sdk`)
- Sysbuild + MCUboot enabled
- Region overlay required: `overlay-us.conf` (carrier 1711) or `overlay-eu.conf` (carrier 1677)
- Console: **115200 8N1**

See also `experiments/01_baseline/README.md`.

## Kconfig

### `prj.conf`

| Option | Value |
|--------|-------|
| `CONFIG_NRF_MODEM_LIB` | y |
| `CONFIG_MODEM_ANTENNA` | n |
| `CONFIG_NRF_MODEM_LINK_BINARY_DECT_PHY` | y |
| `CONFIG_HWINFO` | y |
| `CONFIG_LOG` | y |
| `CONFIG_BOOTLOADER_MCUBOOT` | y |

### RF and experiment options

| Option | Default | Notes |
|--------|---------|-------|
| `CONFIG_CARRIER` | 0 (set in overlay) | Must be non-zero |
| `CONFIG_NETWORK_ID` | 91 | Short network ID = low 8 bits |
| `CONFIG_MCS` | 0 | |
| `CONFIG_TX_POWER` | 13 | Overlay may set 10 |
| `CONFIG_TX_TRANSMISSIONS` | 0 | `0` = run until reset |
| `CONFIG_RX_PERIOD_S` | 5 | |
| `CONFIG_TX_INTERVAL_MS` | 500 | |
| `CONFIG_EXPERIMENT_TEST_MODE_*` | TX_RX | Mode choice |
| `CONFIG_EXPERIMENT_PACKET_SIZE` | 15 | 15–32 bytes |
| `CONFIG_EXPERIMENT_MESSAGE_TYPE` | 1 | Baseline probe |
| `CONFIG_EXPERIMENT_DEST_RECEIVER_ID` | 0 | Broadcast / accept all |
| `CONFIG_EXPERIMENT_DEVICE_ID_OVERRIDE` | n | Optional fixed ID |
| `CONFIG_EXPERIMENT_DEVICE_ID` | 1 | Used when override is enabled |
| `CONFIG_EXPERIMENT_LOG_COMPACT` | y | Prefer `TX:` / `RX:` lines |

### Constants in application code

| Item | Value |
|------|-------|
| HARQ RX processes / expiry | 4 / 5 s |
| LBT period | `NRF_MODEM_DECT_LBT_PERIOD_MAX` |
| RX `rssi_level` | -60 |
| PHY `packet_length` (subslots) | 0x03 |
| Maximum PDC buffer | 32 bytes |

## Device tree

Board description is not shipped inside this experiment. It is provided by:

`…/conexio-firmware-sdk/boards/conexio/stratus_pro/`

Primary include: `conexio_stratus_pro_common.dtsi`

| Item | Setting |
|------|---------|
| Console / shell / mcumgr UART | `&uart0` |
| UART baud rate | 115200 |
| LED | `gpio0` pin 25 |
| Mode button | `gpio0` pin 31 |
| Sensor power regulator | `gpio0` pin 26 |

NS board file: `conexio_stratus_pro_nrf9151_ns.dts`. Apply the Conexio MCUBoot patch once per NCS installation.

## Initialization sequence

1. `nrf_modem_lib_init()`
2. `nrf_modem_dect_phy_event_handler_set(...)`
3. `nrf_modem_dect_phy_init()` → wait
4. `nrf_modem_dect_phy_configure()` (band group derived from carrier) → wait
5. `nrf_modem_dect_phy_activate(LOW_LATENCY)` → wait
6. Resolve `device_id` (hwinfo or Kconfig override)
7. Mode loop (transmit / receive as configured)
8. On finite TX count: deactivate → deinit → modem shutdown

## Node identity

| Layer | Mechanism |
|-------|-----------|
| Local ID | hwinfo (16-bit) or `CONFIG_EXPERIMENT_DEVICE_ID` |
| PHY header | `transmitter_id_hi/lo` = device ID |
| Payload | `device_id` field (same value) |
| Network | Shared `CONFIG_NETWORK_ID` |
| Addressing | `CONFIG_EXPERIMENT_DEST_RECEIVER_ID` (`0` = accept all) |

On receive, the payload `device_id` is used when the checksum is valid; otherwise the PCC transmitter ID is used.

## Scope

This application exercises the DECT NR+ PHY broadcast path. It does not implement FT/PT association, multi-hop routing, or cellular hybrid operation.
