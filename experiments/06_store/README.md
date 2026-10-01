# NR+ store-and-forward (`06_store`)

Custody hop-by-hop firmware for the Experiment 06 store-and-forward testbed. It does not modify `03_topology`.

A node that accepts a frame owns it until the next hop ACKs. A reboot drops the RAM store, and the boot epoch makes that loss visible.

| | |
|---|---|
| Board | `conexio_stratus_pro/nrf9151/ns`, sysbuild |
| Overlay | `overlay-us.conf` or `overlay-eu.conf` (required — carrier is 0 otherwise) |
| Console | 115200 8N1, command `exp` |

How it behaves, every shell key, and the choices you may want to flip: [`docs/06_store_and_forward/IMPLEMENTATION.md`](../../docs/06_store_and_forward/IMPLEMENTATION.md).

Line-by-line run, timings, and each on-air scenario: [`docs/06_store_and_forward/HOW_IT_RUNS.md`](../../docs/06_store_and_forward/HOW_IT_RUNS.md).

Bench procedure and the recorded sink-outage run: [`docs/06_store_and_forward/PROCEDURE.md`](../../docs/06_store_and_forward/PROCEDURE.md), [`reports/06_store/NR_Store_and_Forward_Report.md`](../../reports/06_store/NR_Store_and_Forward_Report.md).

Protocol: [`topo_protocol_spec_v1.md`](topo_protocol_spec_v1.md).

Use `exp sett size 16` on this modem. `size 48` and `size 64` are padded by the PHY slot and rejected. The procedure explains why.


Run it from `experiments/06_store`.
