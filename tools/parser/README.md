# Experiment Log Parsers

## Point-to-Point TX/RX Parser (`parse_tx_rx.py`)
```bash
python parse_tx_rx.py ../../data/01_baseline/run.txt -o ../../data/01_baseline/run.csv
```
`latency_ms` is left blank (clocks are not synchronized across nodes).

## Multi-Hop Performance Parser (`parse_performance.py`)
Parses multi-hop performance benchmark sessions (TX, RX, FORWARD, DELIVER) and computes PDR, throughput, packet rate, RSSI distributions, and jitter:

```bash
python parse_performance.py ../../data/05_performance -o ../../reports/05_performance/summary.csv
```

