#!/usr/bin/env python3
"""Parse TX:/RX: experiment lines from a serial capture into CSV."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

TX_RE = re.compile(
    r"TX:\s*node=(?P<node>\d+)\s+seq=(?P<seq>\d+)\s+size=(?P<size>\d+)\s+"
    r"time=(?P<time>\d+)\s+type=(?P<type>\d+)"
)
RX_RE = re.compile(
    r"RX:\s*node=(?P<node>\d+)\s+seq=(?P<seq>\d+)\s+from=(?P<from>\d+)\s+"
    r"rssi=(?P<rssi>[-\d.]+)\s+time=(?P<time>\d+)\s+tx_time=(?P<tx_time>\d+)\s+"
    r"size=(?P<size>\d+)\s+type=(?P<type>\d+)\s+cs=(?P<cs>\w+)"
)

FIELDS = [
    "timestamp",
    "test_id",
    "source_node",
    "destination_node",
    "sequence_number",
    "distance_m",
    "environment",
    "wall_count",
    "rssi",
    "packet_size",
    "tx_time_ms",
    "rx_time_ms",
    "latency_ms",
    "success",
    "retry_count",
    "hop_count",
    "parent_node",
    "battery_mv",
    "notes",
]


def parse_line(line: str, test_id: str) -> dict | None:
    # Strip optional host timestamp prefix: [HH:MM:SS.mmm]
    host_ts = ""
    m_host = re.match(r"^\[([^\]]+)\]\s*(.*)$", line)
    body = line
    if m_host:
        host_ts = m_host.group(1)
        body = m_host.group(2)

    # Strip Zephyr log prefix if present (... <inf> app: ...)
    if "TX:" in body:
        body = body[body.index("TX:") :]
    elif "RX:" in body:
        body = body[body.index("RX:") :]
    else:
        return None

    row = {k: "" for k in FIELDS}
    row["timestamp"] = host_ts
    row["test_id"] = test_id

    mtx = TX_RE.search(body)
    if mtx:
        row["source_node"] = mtx.group("node")
        row["sequence_number"] = mtx.group("seq")
        row["packet_size"] = mtx.group("size")
        row["tx_time_ms"] = mtx.group("time")
        row["notes"] = f"tx type={mtx.group('type')}"
        return row

    mrx = RX_RE.search(body)
    if mrx:
        row["destination_node"] = mrx.group("node")
        row["source_node"] = mrx.group("from")
        row["sequence_number"] = mrx.group("seq")
        row["rssi"] = mrx.group("rssi")
        row["rx_time_ms"] = mrx.group("time")
        row["tx_time_ms"] = mrx.group("tx_time")
        row["packet_size"] = mrx.group("size")
        row["success"] = "1" if mrx.group("cs") == "ok" else "0"
        row["latency_ms"] = ""  # N/A — clocks not synchronized
        row["notes"] = f"rx type={mrx.group('type')} cs={mrx.group('cs')}"
        return row

    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse experiment TX:/RX: logs to CSV")
    ap.add_argument("logfile", type=Path)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--test-id", default="01_baseline")
    args = ap.parse_args()

    rows: list[dict] = []
    for line in args.logfile.read_text(encoding="utf-8", errors="replace").splitlines():
        row = parse_line(line, args.test_id)
        if row:
            rows.append(row)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
