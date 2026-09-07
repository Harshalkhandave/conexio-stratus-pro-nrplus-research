# Logging format — baseline firmware

## Clock model

| Clock | Location | Meaning |
|-------|----------|---------|
| `tx_time` / `tx_time_ms` | PDU and TX log | Milliseconds since **sender** boot |
| `time` on RX line | RX log only | Milliseconds since **receiver** boot |
| Host `[HH:MM:SS.mmm]` | Optional `tools/logger` prefix | Capture PC time (not RF latency) |
| Modem `evt->time` | Debug only | Modem time ticks; not used as a primary metric |

Nodes do **not** share a synchronized wall clock.  
Do not interpret `rx_time − tx_time` as one-way latency. Use sequence continuity and delivery ratio for reliability analysis; use an RTT-style measurement if latency is required.

## Structured log lines

### Transmit

```text
TX: node=<id> seq=<n> size=<B> time=<tx_ms> type=<t>
```

Emitted when the packet is built and queued (before waiting for TX complete).

### Receive

```text
RX: node=<local_id> seq=<n> from=<id> rssi=<int>.<frac> time=<rx_ms> tx_time=<ms> size=<B> type=<t> cs=ok|fail
```

- `rssi` derived from modem `rssi_2` (half-dBm units → `d.d`)
- `cs=fail` on short frames or XOR mismatch
- Optional warning: `RX gap: from=… prev_seq=… seq=…` on sequence discontinuity

### Startup

```text
NR+ Experimental Firmware v1.1 (01_baseline)
mode=… carrier=… shell=… wait_for_start=…
device_id=…
Commands: exp status | exp sett | exp start [count] | exp stop
```

With `CONFIG_EXPERIMENT_LOG_COMPACT=n`, additional diagnostic lines may appear.

### Run summary

Printed when a run ends (`exp stop`, TX count reached, or error):

```text
SUMMARY: role=tx reason=count_reached device_id=… sent=1000 count_cfg=1000
SUMMARY: role=rx reason=stop device_id=… from=… ok=… fail=… gaps=… rssi_min=… rssi_avg=… rssi_max=…
```

Use TX `sent` and RX `ok` for packet delivery ratio with asymmetric roles.

## Host capture

```text
python tools/logger/serial_logger.py COM9 --out data/01_baseline/run.txt
```

## CSV export

```text
python tools/parser/parse_tx_rx.py data/01_baseline/run.txt -o data/01_baseline/run.csv
```

The parser populates fields available from firmware logs. The `latency_ms` column is left empty until a shared time base or RTT method is introduced.
