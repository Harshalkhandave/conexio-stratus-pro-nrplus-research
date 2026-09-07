#!/usr/bin/env python3
"""
Interactive range campaign runner for NR+ baseline firmware.

Your job: place the boards and confirm when ready.
The script: talks to TX/RX over serial, sets params, starts/stops runs,
captures logs, parses SUMMARY lines, appends results CSV.

Example:
  python range_campaign.py --tx COM5 --rx COM6 --matrix matrix.example.yaml

Requires boards flashed as tx_only (TX) and rx_only (RX), same region overlay.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Install pyserial:  python -m pip install -r requirements.txt")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Install PyYAML:  python -m pip install -r requirements.txt")
    sys.exit(1)


SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)")
KV_RE = re.compile(r"(\w+)=([^\s]+)")

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "02_range"


class BoardSession:
    def __init__(self, port: str, baud: int, label: str, log_path: Path):
        self.port = port
        self.label = label
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ser = serial.Serial(port, baudrate=baud, timeout=0.2)
        time.sleep(0.4)
        self._ser.reset_input_buffer()
        self._buf = bytearray()
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._log = self.log_path.open("a", encoding="utf-8", errors="replace")
        self._log.write(
            f"===== {label} start {datetime.now().isoformat(timespec='seconds')} "
            f"port={port} =====\n"
        )
        self._log.flush()
        self._thread.start()

    def _reader(self) -> None:
        while not self._stop.is_set():
            chunk = self._ser.read(256)
            if not chunk:
                continue
            self._buf.extend(chunk)
            while True:
                nl = self._buf.find(b"\n")
                if nl < 0:
                    break
                raw = bytes(self._buf[: nl + 1])
                del self._buf[: nl + 1]
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                text = f"[{ts}] {line}"
                with self._lock:
                    self._lines.append(line)
                    self._log.write(text + "\n")
                    self._log.flush()
                print(f"{self.label}: {line}", flush=True)

    def write_line(self, cmd: str) -> None:
        payload = (cmd.strip() + "\r\n").encode("utf-8")
        self._ser.write(payload)
        self._ser.flush()
        time.sleep(0.15)

    def clear_lines(self) -> None:
        with self._lock:
            self._lines.clear()

    def wait_for_summary(self, timeout_s: float) -> dict | None:
        deadline = time.time() + timeout_s
        seen = 0
        while time.time() < deadline:
            with self._lock:
                new = self._lines[seen:]
                seen = len(self._lines)
            for line in new:
                # Strip Zephyr log prefix if present
                idx = line.find("SUMMARY:")
                if idx < 0:
                    continue
                body = line[idx:]
                m = SUMMARY_RE.search(body)
                if not m:
                    continue
                return dict(KV_RE.findall(m.group(1)))
            time.sleep(0.1)
        return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        if self._ser.is_open:
            self._ser.close()
        self._log.close()


def list_ports_and_exit() -> int:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return 1
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device:10}  {p.description}")
    return 0


def confirm(prompt: str) -> bool:
    try:
        ans = input(f"\n{prompt} [Y/n] ").strip().lower()
    except EOFError:
        return False
    return ans in ("", "y", "yes")


def apply_settings(board: BoardSession, defaults: dict, test: dict) -> None:
    interval = test.get("interval_ms", defaults.get("interval_ms", 200))
    power = test.get("power", defaults.get("power", 10))
    mcs = test.get("mcs", defaults.get("mcs", 0))
    size = test.get("size", defaults.get("size", 15))

    board.write_line("exp stop")
    time.sleep(0.5)
    board.write_line(f"exp sett interval {interval}")
    board.write_line(f"exp sett power {power}")
    board.write_line(f"exp sett mcs {mcs}")
    board.write_line(f"exp sett size {size}")
    time.sleep(0.3)


def expected_tx_duration_s(count: int, interval_ms: int) -> float:
    # Rough upper bound: count * interval + TX/RX PHY overhead margin
    return (count * interval_ms / 1000.0) + 15.0


def append_result(csv_path: Path, row: dict, fieldnames: list[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if new_file:
            w.writeheader()
        w.writerow(row)


def run_campaign(args: argparse.Namespace) -> int:
    matrix_path = Path(args.matrix)
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    defaults = matrix.get("defaults", {})
    tests = matrix.get("tests", [])
    if not tests:
        print("No tests in matrix.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    results_csv = out_dir / "results.csv"

    print(f"Output directory: {out_dir}")
    print("Open nRF Serial Terminal / other monitors must be CLOSED on these ports.\n")

    tx = BoardSession(args.tx, args.baud, "TX", out_dir / "tx_full.txt")
    rx = BoardSession(args.rx, args.baud, "RX", out_dir / "rx_full.txt")

    fieldnames = [
        "test_id",
        "distance_m",
        "wall_count",
        "environment",
        "orientation",
        "interval_ms",
        "power",
        "mcs",
        "size",
        "count",
        "tx_sent",
        "rx_ok",
        "rx_fail",
        "rx_gaps",
        "rssi_min",
        "rssi_avg",
        "rssi_max",
        "pdr_pct",
        "notes",
        "tx_summary",
        "rx_summary",
    ]

    try:
        for i, test in enumerate(tests, start=1):
            tid = test.get("id", f"test_{i}")
            distance = test.get("distance_m", "")
            walls = test.get("wall_count", "")
            env = test.get("environment", "")
            orient = test.get("orientation", "nominal")
            count = int(test.get("count", defaults.get("count", 1000)))
            interval = int(test.get("interval_ms", defaults.get("interval_ms", 200)))
            settle = float(test.get("settle_s", defaults.get("settle_s", 3)))

            print("\n" + "=" * 60)
            print(f"TEST {i}/{len(tests)}: {tid}")
            print(f"  Place boards: distance={distance} m  walls={walls}  env={env}  orient={orient}")
            print("=" * 60)

            if not confirm("Boards in position? Continue"):
                print("Skipped.")
                continue

            # Prepare both boards (stop + sett)
            apply_settings(rx, defaults, test)
            apply_settings(tx, defaults, test)

            tx.clear_lines()
            rx.clear_lines()

            # RX listens for the whole run (count 0 = forever)
            rx.write_line("exp start 0")
            time.sleep(0.5)
            # TX finite run
            tx.write_line(f"exp start {count}")

            timeout = expected_tx_duration_s(count, interval) + settle
            print(f"Waiting for TX SUMMARY (timeout {timeout:.0f}s)...")
            tx_sum = tx.wait_for_summary(timeout)

            # Stop RX to freeze counters / print SUMMARY
            rx.write_line("exp stop")
            rx_sum = rx.wait_for_summary(30.0)

            tx_sent = int(tx_sum.get("sent", 0)) if tx_sum else 0
            rx_ok = int(rx_sum.get("ok", 0)) if rx_sum else 0
            pdr = (100.0 * rx_ok / tx_sent) if tx_sent else 0.0

            row = {
                "test_id": tid,
                "distance_m": distance,
                "wall_count": walls,
                "environment": env,
                "orientation": orient,
                "interval_ms": interval,
                "power": test.get("power", defaults.get("power", 10)),
                "mcs": test.get("mcs", defaults.get("mcs", 0)),
                "size": test.get("size", defaults.get("size", 15)),
                "count": count,
                "tx_sent": tx_sent,
                "rx_ok": rx_ok,
                "rx_fail": rx_sum.get("fail", "") if rx_sum else "",
                "rx_gaps": rx_sum.get("gaps", "") if rx_sum else "",
                "rssi_min": rx_sum.get("rssi_min", "") if rx_sum else "",
                "rssi_avg": rx_sum.get("rssi_avg", "") if rx_sum else "",
                "rssi_max": rx_sum.get("rssi_max", "") if rx_sum else "",
                "pdr_pct": f"{pdr:.2f}",
                "notes": "" if tx_sum and rx_sum else "missing SUMMARY",
                "tx_summary": str(tx_sum or ""),
                "rx_summary": str(rx_sum or ""),
            }
            append_result(results_csv, row, fieldnames)
            print(
                f"Result: tx_sent={tx_sent} rx_ok={rx_ok} PDR={pdr:.2f}% "
                f"(saved -> {results_csv.name})"
            )

            if not confirm("Continue to next test?"):
                break

    finally:
        tx.close()
        rx.close()

    print(f"\nCampaign finished. Results: {results_csv}")
    print(f"Raw logs: {out_dir}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="NR+ range campaign (you confirm placement)")
    ap.add_argument("--list", action="store_true", help="List COM ports")
    ap.add_argument("--tx", help="TX board serial port (tx_only firmware)")
    ap.add_argument("--rx", help="RX board serial port (rx_only firmware)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument(
        "--matrix",
        default=str(Path(__file__).with_name("matrix.example.yaml")),
        help="YAML test matrix",
    )
    ap.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help="Output root (default: data/02_range)",
    )
    args = ap.parse_args()

    if args.list:
        return list_ports_and_exit()
    if not args.tx or not args.rx:
        ap.print_help()
        print("\nExample: python range_campaign.py --tx COM5 --rx COM6")
        return 1
    return run_campaign(args)


if __name__ == "__main__":
    raise SystemExit(main())
