# Serial logger

Capture UART output from a Stratus board to the terminal and a text file.

```text
python -m pip install -r requirements.txt
python serial_logger.py --list
python serial_logger.py COM9
python serial_logger.py COM9 --out ../../data/01_baseline/run1.txt
```

Default output path: `data/01_baseline/baseline_YYYYMMDD_HHMMSS.txt`

Only one process may open a given COM port on Windows.
