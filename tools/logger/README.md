# Serial logger

Capture UART from a Stratus board to the terminal **and** a text file.  
By default you can **type Zephyr shell commands** (`exp status`, `exp start`, …) the same way as in a serial terminal; only one process can own the COM port on Windows.

```text
python -m pip install -r requirements.txt
python serial_logger.py --list
python serial_logger.py COM9
python serial_logger.py COM9 --out ../../data/03_topology/run_c.txt
python serial_logger.py COM9 --no-interact    # RX log only
```

Default output path: `data/01_baseline/baseline_YYYYMMDD_HHMMSS.txt`

## Timestamps

Each logged line is prefixed with **this PC’s local wall clock** (`HH:MM:SS.mmm`), from `datetime.now()` — not the board’s `k_uptime` / `time=` in the firmware log.

| Clock | Where | Use |
|-------|--------|-----|
| `[15:42:01.123]` prefix | Host (logger) | Align events across boards **if one PC** logs all COM ports |
| `time=589164` in firmware line | Board uptime ms | Per-board only; not sync’d across A/B/C |

Typed commands are logged as `>>> exp start` with the same host timestamp (useful for route-establishment t₀).

## Notes

- Close nRF Serial Terminal / other apps on that COM port first.
- For comparable timing on A/B/C, run three logger windows on **one** PC.
