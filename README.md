# Conexio Stratus Pro — DECT NR+ Research

Engineering workspace for characterizing **DECT NR+** on the [Conexio Stratus Pro](https://docs.conexiotech.com/) (nRF9151): RF behavior, reliability, topology, and product fit versus cellular / other IoT links.

| Item | Value |
|------|--------|
| Platform | Conexio Stratus Pro / nRF9151 (non-secure) |
| SDK | nRF Connect SDK **v3.2.1** |
| Board package | `conexio-firmware-sdk` (see Conexio docs) |

## Current firmware

**[`experiments/01_baseline/`](experiments/01_baseline/)** — NR+ experimental firmware (instrumented PHY baseline): sequenced packets, TX/RX timestamps, structured serial logs, configurable test roles, optional `exp` shell.

Supporting material:

- [`docs/01_baseline/`](docs/01_baseline/) — configuration, packet format, logging  
- [`tools/`](tools/) — serial capture and CSV parsing  
- [`data/`](data/) — captured logs and datasets  
- [`reports/`](reports/) — written results  

## Build & flash (recommended)

Conexio recommends building with the **nRF Connect extension for VS Code / Cursor**, not the CLI as the primary path.

Follow: [Compiling Applications with nRF Connect Extension for VS Code](https://docs.conexiotech.com/master/building-and-programming-an-application/compiling-applications-with-nrf-connect-extension-for-vs-code.md)

Summary:

1. Install NCS v3.2.1 and the [Conexio firmware SDK](https://docs.conexiotech.com/master/building-and-programming-an-application/fetch-conexio-firmware-sdk-and-board-definition-files.md) (including the MCUBoot patch).
2. In nRF Connect settings → **Board Roots**, add your `conexio-firmware-sdk` path (example on Windows: `C:\nordic\ncs\v3.2.1\conexio-firmware-sdk`).
3. **Open an existing application** → select `experiments/01_baseline`.
4. **Add Build Configuration** → enable custom boards → select `conexio_stratus_pro/nrf9151/ns` → use **sysbuild**.
5. Add Extra Kconfig fragments as needed, e.g. `overlay-us.conf` or `overlay-eu.conf` (region), plus optional role overlays documented in the experiment README.
6. Build, put the device in **DFU mode**, flash with `newtmgr` / the flow in Conexio’s guide. Console: **115200 8N1**.

Full application details, overlays, and bring-up checks: [`experiments/01_baseline/README.md`](experiments/01_baseline/README.md).

## Repository layout

| Path | Purpose |
|------|---------|
| `experiments/01_baseline/` | Instrumented NR+ baseline firmware (+ `exp` shell) |
| `experiments/02_range/` | Range-test procedure and notes |
| `tools/logger/` | Serial log capture |
| `tools/parser/` | Parse `TX:` / `RX:` lines to CSV |
| `data/` | Raw captures and derived datasets |
| `docs/01_baseline/` | Baseline firmware documentation |
| `reports/` | Experiment reports |

Additional experiment directories (range, topology, healing, …) can be added alongside `01_baseline` as work progresses.

## Regulatory note

DECT NR+ uses regulated spectrum. Use the US/EU carrier overlays only where you are permitted to transmit, and follow local rules.
