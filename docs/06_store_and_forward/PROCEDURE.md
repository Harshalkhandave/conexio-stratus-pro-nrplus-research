# Experiment 06: Store-and-Forward Outage Procedure

This is the bench procedure for hop-by-hop custody on `experiments/06_store`. It replaces the open-loop forward path in `03_topology` for this experiment only. Do not flash `06_store` and `03_topology` on the same network id.

The firmware plan is [`DESIGN_AND_PLAN.md`](DESIGN_AND_PLAN.md). What the image actually does is [`IMPLEMENTATION.md`](IMPLEMENTATION.md). The recorded run is [`reports/06_store/NR_Store_and_Forward_Report.md`](../../reports/06_store/NR_Store_and_Forward_Report.md).

---

## 1. Prerequisites

### Hardware
- 3× Conexio Stratus Pro (nRF9151), NCS v3.2.1, sysbuild, region overlay (`overlay-us.conf` on this bench, carrier 1711).
- Serial 115200 8N1. This bench: sink on `COM7`, the other two boards through `socket://10.0.0.139:7777` and `socket://10.0.0.139:7778`.
- The script assigns roles from the modem short id: lowest id is the sink, middle id is the relay, highest id is the source. On this bench that is source `56992`, relay `44720`, sink `14402`.

### Firmware
All three boards run `experiments/06_store`. Console command is `exp`.

### Payload size
`exp sett size` is the application payload, not the whole PDC. The modem pads a received buffer out to the PHY slot. DATA currently treats that pad as payload.

| `size` | Frame | Slot code | Result on this modem |
|---|---|---|---|
| 16 | 32 bytes | `0x03` | Accepted. This is the procedure setting. |
| 48 | 64 bytes | `0x07` | `BAD_FRAME`, false `QUEUE_FULL` |
| 64 | 80 bytes | `0x0F` | `BAD_FRAME`, false `QUEUE_FULL` |

Stay at `size 16` until the codec carries an explicit length and ignores the pad. Details are in [`HOW_IT_RUNS.md`](HOW_IT_RUNS.md) §10.

### What a pass looks like
- Sink `DELIVER` sequence numbers are contiguous and increasing for the whole run.
- While the sink is stopped, the sink log has no new `DELIVER`.
- The relay depth climbs by about one frame per second and returns to zero after the sink is restored.
- `QUEUE_FULL` appears only after the relay telemetry pool is full (320 small slots, 32 reserved for alarms, so 288 telemetry frames). The source keeps that frame. There is no `CUSTODY_BROKEN` under policy `reject`.
- No `BAD_FRAME`, `RX_GAP`, `DROP_OVERFLOW`, or `DROP_EXPIRED`.

`exp start` zeros that node's counters and flushes its store. The sink is stopped and started again for each outage, so a later `delivered=` is the count since that start, not the run total. The run total is the set of `DELIVER` sequence numbers in the log.

---

## 2. Automated run

From `tools/logger`, with the logger virtualenv (system Python on this machine does not have pyserial):

```powershell
cd tools\logger
.\.venv\Scripts\python.exe sf_auto_test.py COM7 socket://10.0.0.139:7777 socket://10.0.0.139:7778
```

The script takes about 12 minutes. It does not need shell typing. On every board it forces `exp stop`, `exp flush`, role, route, `size 16`, `interval 1000`, `count 0`, `assume_up off`, `ack_timeout 400`, and `policy reject`, even when the role already matches. The source is `direct off` with a static route to the sink via the relay.

Phases:

1. `exp status` before start.
2. About 30 s with the sink up.
3. `exp status`, then the sink is stopped for 180 s and started again. The script waits until the sink has been quiet for 8 s, or 180 s, whichever comes first.
4. `exp status`.
5. The sink is stopped for 300 s and started again. Same drain wait.
6. `exp status`, then `exp stop` on all three boards.

Logs land in `tools/logger/sf_logs/<YYYYMMDD_HHMMSS>/` as `source.txt`, `relay.txt`, `sink.txt`, and `report.txt`. Copy that folder to `data/06_store/<stamp>/` before treating it as the dataset. `report.txt` prints `PASS` when the sink sequences it saw are contiguous, both outages produced new deliveries, and the 5-minute outage produced at least one `QUEUE_FULL`.

---

## 3. What this procedure does not cover

Still open from the plan, and not claimed by the 2026-09-30 run:

- Clean 1-hop, 100 packets, with `ack_timeout` frozen from a measured RTT.
- A finite 2-hop run of 100 packets with the sink left up the whole time.
- Relay reboot mid-run (`NEIGHBOR_RESET` / `RX_GAP` for frames that were only in RAM).
- Relay powered down for 5 minutes (this procedure stops the sink).
- `policy drop_oldest` and a `CUSTODY_BROKEN` count that matches the sink gap.
- Payload above 16 bytes.
