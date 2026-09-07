#!/usr/bin/env python3
"""Merge tx_results.csv + rx_results.csv from a split-host session into results.csv."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {row["test_id"]: row for row in csv.DictReader(f)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dir", type=Path, help="data/02_range/<session>")
    args = ap.parse_args()

    tx = load(args.session_dir / "tx_results.csv")
    rx = load(args.session_dir / "rx_results.csv")
    ids = sorted(set(tx) | set(rx))
    out = args.session_dir / "results.csv"

    fields = [
        "test_id",
        "distance_m",
        "wall_count",
        "environment",
        "orientation",
        "interval_ms",
        "power",
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
    ]

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for tid in ids:
            t = tx.get(tid, {})
            r = rx.get(tid, {})
            try:
                sent = int(t.get("tx_sent") or 0)
                ok = int(r.get("rx_ok") or 0)
                pdr = f"{(100.0 * ok / sent):.2f}" if sent else ""
            except ValueError:
                sent, ok, pdr = t.get("tx_sent", ""), r.get("rx_ok", ""), ""
            w.writerow(
                {
                    "test_id": tid,
                    "distance_m": t.get("distance_m") or r.get("distance_m", ""),
                    "wall_count": t.get("wall_count") or r.get("wall_count", ""),
                    "environment": t.get("environment") or r.get("environment", ""),
                    "orientation": t.get("orientation") or r.get("orientation", ""),
                    "interval_ms": t.get("interval_ms", ""),
                    "power": t.get("power", ""),
                    "count": t.get("count", ""),
                    "tx_sent": sent,
                    "rx_ok": ok,
                    "rx_fail": r.get("rx_fail", ""),
                    "rx_gaps": r.get("rx_gaps", ""),
                    "rssi_min": r.get("rssi_min", ""),
                    "rssi_avg": r.get("rssi_avg", ""),
                    "rssi_max": r.get("rssi_max", ""),
                    "pdr_pct": pdr,
                    "notes": ";".join(
                        x for x in [t.get("notes", ""), r.get("notes", "")] if x
                    ),
                }
            )

    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
