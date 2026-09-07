#!/usr/bin/env python3
"""
RX-side helper when TX and RX boards are on different PCs.

You: confirm placement, then confirm when TX has finished.
Script: configures RX, starts listen, stops, saves SUMMARY + log.

Example:
  python range_rx.py --port COM6 --matrix matrix.yaml --test los_5m
  python range_rx.py --port COM6 --matrix matrix.yaml --all
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
    print("pip install pyserial PyYAML")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("pip install pyserial PyYAML")
    sys.exit(1)

SUMMARY_RE = re.compile(r"SUMMARY:\s*(.+)")
KV_RE = re.compile(r"(\w+)=([^\s]+)")
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = REPO_ROOT / "data" / "02_range"


class SerialTap:
    def __init__(self, port: str, baud: int, log_path: Path):
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._ser = serial.Serial(port, baudrate=baud, timeout=0.2)
        time.sleep(0.4)
        self._ser.reset_input_buffer()
        self._buf = bytearray()
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._log = log_path.open("a", encoding="utf-8", errors="replace")
        self._thread = threading.Thread(target=self._reader, daemon=True)
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
                with self._lock:
                    self._lines.append(line)
                    self._log.write(f"[{ts}] {line}\n")
                    self._log.flush()
                print(f"RX: {line}", flush=True)

    def write_line(self, cmd: str) -> None:
        self._ser.write((cmd.strip() + "\r\n").encode("utf-8"))
        self._ser.flush()
        time.sleep(0.15)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def wait_summary(self, timeout_s: float) -> dict | None:
        deadline = time.time() + timeout_s
        seen = 0
        while time.time() < deadline:
            with self._lock:
                chunk = self._lines[seen:]
                seen = len(self._lines)
            for line in chunk:
                idx = line.find("SUMMARY:")
                if idx < 0:
                    continue
                m = SUMMARY_RE.search(line[idx:])
                if m:
                    return dict(KV_RE.findall(m.group(1)))
            time.sleep(0.1)
        return None

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        if self._ser.is_open:
            self._ser.close()
        self._log.close()


def confirm(msg: str) -> bool:
    try:
        a = input(f"\n{msg} [Y/n] ").strip().lower()
    except EOFError:
        return False
    return a in ("", "y", "yes")


def apply_sett(board: SerialTap, defaults: dict, test: dict) -> None:
    board.write_line("exp stop")
    time.sleep(0.4)
    board.write_line(f"exp sett interval {test.get('interval_ms', defaults.get('interval_ms', 200))}")
    board.write_line(f"exp sett power {test.get('power', defaults.get('power', 10))}")
    board.write_line(f"exp sett mcs {test.get('mcs', defaults.get('mcs', 0))}")
    board.write_line(f"exp sett size {test.get('size', defaults.get('size', 15))}")
    time.sleep(0.2)


def append_row(path: Path, row: dict, fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if new:
            w.writeheader()
        w.writerow(row)


def main() -> int:
    ap = argparse.ArgumentParser(description="RX PC range helper (separate from TX PC)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--port", help="RX board COM port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--matrix", default=str(Path(__file__).with_name("matrix.example.yaml")))
    ap.add_argument("--test", help="Single test id from matrix")
    ap.add_argument("--all", action="store_true", help="Run all tests in matrix")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--session", default="", help="Shared session name (same on TX PC)")
    args = ap.parse_args()

    if args.list:
        for p in list_ports.comports():
            print(f"{p.device:10}  {p.description}")
        return 0
    if not args.port or (not args.test and not args.all):
        ap.print_help()
        print("\nExample: python range_rx.py --port COM6 --matrix matrix.yaml --all")
        print("         python range_rx.py --port COM6 --matrix matrix.yaml --test los_5m")
        return 1

    matrix = yaml.safe_load(Path(args.matrix).read_text(encoding="utf-8"))
    defaults = matrix.get("defaults", {})
    tests = matrix.get("tests", [])
    if args.test:
        tests = [t for t in tests if t.get("id") == args.test]
        if not tests:
            print(f"Test id not found: {args.test}")
            return 1

    session = args.session or datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.out) / session
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "rx_results.csv"
    print(f"RX session folder: {out_dir}")
    print(f"Use the SAME --session on the TX PC: {session}")

    fields = [
        "test_id",
        "distance_m",
        "wall_count",
        "environment",
        "orientation",
        "rx_ok",
        "rx_fail",
        "rx_gaps",
        "rssi_min",
        "rssi_avg",
        "rssi_max",
        "rx_summary",
        "notes",
    ]

    board = SerialTap(args.port, args.baud, out_dir / "rx_full.txt")
    try:
        for i, test in enumerate(tests, 1):
            tid = test.get("id", f"test_{i}")
            print("\n" + "=" * 60)
            print(f"RX TEST {i}/{len(tests)}: {tid}")
            print(
                f"  Place boards: distance={test.get('distance_m')} m  "
                f"walls={test.get('wall_count')}  env={test.get('environment')}"
            )
            print("=" * 60)
            if not confirm("Boards placed? Start RX listen"):
                print("Skipped.")
                continue

            apply_sett(board, defaults, test)
            board.clear()
            board.write_line("exp start 0")
            print("RX listening. On the TX PC, start the same test id now.")
            if not confirm("TX finished (TX SUMMARY seen)? Stop RX and save"):
                board.write_line("exp stop")
                print("Aborted without waiting for SUMMARY.")
                continue

            board.write_line("exp stop")
            summary = board.wait_summary(30.0)
            row = {
                "test_id": tid,
                "distance_m": test.get("distance_m", ""),
                "wall_count": test.get("wall_count", ""),
                "environment": test.get("environment", ""),
                "orientation": test.get("orientation", ""),
                "rx_ok": summary.get("ok", "") if summary else "",
                "rx_fail": summary.get("fail", "") if summary else "",
                "rx_gaps": summary.get("gaps", "") if summary else "",
                "rssi_min": summary.get("rssi_min", "") if summary else "",
                "rssi_avg": summary.get("rssi_avg", "") if summary else "",
                "rssi_max": summary.get("rssi_max", "") if summary else "",
                "rx_summary": str(summary or ""),
                "notes": "" if summary else "missing SUMMARY",
            }
            append_row(csv_path, row, fields)
            print(f"Saved RX result -> {csv_path}")
            if args.all and not confirm("Continue to next RX test?"):
                break
    finally:
        board.close()

    print(f"\nDone. Merge with TX CSV later (same session={session}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
