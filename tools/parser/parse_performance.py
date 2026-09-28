#!/usr/bin/env python3
"""Parse DECT NR+ multi-hop performance logs and compute metrics: PDR, throughput, RSSI, jitter.

Uses on-board microsecond hardware timestamps (time_us) for rigorous on-air timing
and cadence, and correlates Node A TX records with Node C DELIVER records.
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import re
from pathlib import Path


def mean(lst: list[float]) -> float:
    return sum(lst) / len(lst) if lst else 0.0


def stddev(lst: list[float]) -> float:
    if len(lst) < 2:
        return 0.0
    m = mean(lst)
    return math.sqrt(sum((x - m) ** 2 for x in lst) / len(lst))


def percentile(lst: list[float], p: float) -> float:
    if not lst:
        return 0.0
    s = sorted(lst)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return s[int(k)]
    return s[int(f)] * (c - k) + s[int(c)] * (k - f)


def parse_session(session_dir: Path) -> dict:
    tx_file = session_dir / "Node_A_log.txt"
    fwd_file = session_dir / "Node_B_log.txt"
    deliv_file = session_dir / "Node_C_log.txt"

    tx_lines: list[str] = []
    if tx_file.exists():
        with tx_file.open("r", encoding="utf-8", errors="replace") as f:
            tx_lines = [line.strip() for line in f if "TX:" in line]

    fwd_lines: list[str] = []
    if fwd_file.exists():
        with fwd_file.open("r", encoding="utf-8", errors="replace") as f:
            fwd_lines = [line.strip() for line in f if "FORWARD:" in line]

    deliv_lines: list[str] = []
    if deliv_file.exists():
        with deliv_file.open("r", encoding="utf-8", errors="replace") as f:
            deliv_lines = [line.strip() for line in f if "DELIVER:" in line]

    # Hop breakdown and RSSI
    rssi_0: list[float] = []
    rssi_1: list[float] = []
    deliv_records: list[dict] = []

    for line in deliv_lines:
        m_hop = re.search(r"hops?=(\d+)", line)
        m_rssi = re.search(r"rssi=(-?[\d\.]+)", line)
        m_seq = re.search(r"seq=(\d+)", line)
        m_us = re.search(r"time_us=(\d+)", line)
        hop = int(m_hop.group(1)) if m_hop else 0
        r_val = float(m_rssi.group(1)) if m_rssi else 0.0
        seq = int(m_seq.group(1)) if m_seq else -1
        t_us = int(m_us.group(1)) if m_us else 0

        deliv_records.append({"seq": seq, "hop": hop, "rssi": r_val, "time_us": t_us, "raw": line})
        if hop == 1:
            rssi_1.append(r_val)
        else:
            rssi_0.append(r_val)

    # Detect bursts in TX by sequence restart (seq=0) or large time gap > 1.5s
    tx_bursts: list[list[dict]] = []
    curr_tx_burst: list[dict] = []
    for line in tx_lines:
        m_seq = re.search(r"seq=(\d+)", line)
        m_sz = re.search(r"size=(\d+)", line)
        m_us = re.search(r"time_us=(\d+)", line)
        if m_seq and m_us:
            seq = int(m_seq.group(1))
            sz = int(m_sz.group(1)) if m_sz else 32
            u = int(m_us.group(1))
            if curr_tx_burst and (seq == 0 or (u - curr_tx_burst[-1]["time_us"]) > 2.0e6):
                tx_bursts.append(curr_tx_burst)
                curr_tx_burst = [{"seq": seq, "size": sz, "time_us": u, "raw": line}]
            else:
                curr_tx_burst.append({"seq": seq, "size": sz, "time_us": u, "raw": line})
    if curr_tx_burst:
        tx_bursts.append(curr_tx_burst)

    # Detect bursts in DELIVER by matching sequence restarts (seq=0) or time_us gap > 2.0s
    deliv_bursts: list[list[dict]] = []
    curr_d_burst: list[dict] = []
    for rec in deliv_records:
        if curr_d_burst and (rec["seq"] == 0 or (rec["time_us"] - curr_d_burst[-1]["time_us"]) > 2.0e6):
            deliv_bursts.append(curr_d_burst)
            curr_d_burst = [rec]
        else:
            curr_d_burst.append(rec)
    if curr_d_burst:
        deliv_bursts.append(curr_d_burst)

    burst_stats: list[dict] = []
    num_bursts = max(len(tx_bursts), len(deliv_bursts))

    for idx in range(num_bursts):
        tb = tx_bursts[idx] if idx < len(tx_bursts) else []
        db = deliv_bursts[idx] if idx < len(deliv_bursts) else []

        sz = tb[0]["size"] if tb else 32
        sent_pkts = len(tb)
        deliv_pkts = len(db)
        burst_pdr = (deliv_pkts / sent_pkts * 100.0) if sent_pkts > 0 else 100.0

        # Calculate exact duration using on-board microsecond timer (time_us)
        # Duration is the span from first to last delivered packet
        if len(db) >= 2:
            dur_hw_s = (db[-1]["time_us"] - db[0]["time_us"]) / 1.0e6
            cadence_ms = (dur_hw_s / (len(db) - 1)) * 1000.0
            pkt_s = len(db) / dur_hw_s if dur_hw_s > 0 else 0.0
            # Application goodput: bits of application payload delivered per second
            bits = deliv_pkts * sz * 8
            throughput_kbps = (bits / dur_hw_s) / 1000.0 if dur_hw_s > 0 else 0.0
        else:
            dur_hw_s = 0.0
            cadence_ms = 0.0
            pkt_s = 0.0
            throughput_kbps = 0.0

        burst_stats.append({
            "burst_id": idx + 1,
            "packets_sent": sent_pkts,
            "packets_delivered": deliv_pkts,
            "pdr_pct": round(burst_pdr, 2),
            "size_bytes": sz,
            "hw_duration_s": round(dur_hw_s, 4),
            "cadence_ms": round(cadence_ms, 2),
            "packet_rate_pkts": round(pkt_s, 1),
            "throughput_kbps": round(throughput_kbps, 2),
        })

    total_sent = len(tx_lines)
    total_deliv = len(deliv_lines)
    pdr = (total_deliv / total_sent * 100.0) if total_sent > 0 else 0.0

    return {
        "session": session_dir.name,
        "total_sent": total_sent,
        "total_delivered": total_deliv,
        "total_forwarded": len(fwd_lines),
        "pdr": round(pdr, 2),
        "hops_0_count": len(rssi_0),
        "hops_1_count": len(rssi_1),
        "mean_rssi_direct": round(mean(rssi_0), 1) if rssi_0 else None,
        "mean_rssi_relayed": round(mean(rssi_1), 1) if rssi_1 else None,
        "bursts": burst_stats,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse DECT NR+ performance benchmark sessions")
    parser.add_argument("data_dir", type=Path, help="Directory containing performance benchmark sessions")
    parser.add_argument("-o", "--out", type=Path, default=None, help="Output CSV path for summary")
    args = parser.parse_args()

    sessions: list[Path] = []
    if (args.data_dir / "Node_A_log.txt").exists():
        sessions = [args.data_dir]
    else:
        sessions = [p for p in sorted(args.data_dir.iterdir()) if p.is_dir() and (p / "Node_A_log.txt").exists()]

    if not sessions:
        print(f"No valid session directories found in {args.data_dir}")
        return 1

    results: list[dict] = []
    csv_rows: list[dict] = []

    for s in sessions:
        res = parse_session(s)
        results.append(res)
        print("=" * 65)
        print(f"Session: {res['session']}")
        print(f"  Sent: {res['total_sent']} | Delivered: {res['total_delivered']} | Fwd: {res['total_forwarded']} | PDR: {res['pdr']}%")
        print(f"  Direct 1-Hop  (hops=0): {res['hops_0_count']} pkts (Mean RSSI: {res['mean_rssi_direct']} dBm)")
        print(f"  Relayed 2-Hop (hops=1): {res['hops_1_count']} pkts (Mean RSSI: {res['mean_rssi_relayed']} dBm)")
        for b in res["bursts"]:
            print(f"    Burst #{b['burst_id']}: Sent={b['packets_sent']}, Deliv={b['packets_delivered']} ({b['pdr_pct']}%), Size={b['size_bytes']}B, "
                  f"Dur={b['hw_duration_s']}s, Cadence={b['cadence_ms']}ms -> {b['throughput_kbps']} kbps ({b['packet_rate_pkts']} pkt/s)")
            csv_rows.append({
                "session": res["session"],
                "burst_id": b["burst_id"],
                "packets_sent": b["packets_sent"],
                "packets_delivered": b["packets_delivered"],
                "pdr_pct": b["pdr_pct"],
                "size_bytes": b["size_bytes"],
                "duration_s": b["hw_duration_s"],
                "cadence_ms": b["cadence_ms"],
                "throughput_kbps": b["throughput_kbps"],
                "packet_rate_pkts": b["packet_rate_pkts"],
                "mean_rssi_direct": res["mean_rssi_direct"],
                "mean_rssi_relayed": res["mean_rssi_relayed"],
            })

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8", newline="") as f:
            fields = [
                "session", "burst_id", "packets_sent", "packets_delivered", "pdr_pct",
                "size_bytes", "duration_s", "cadence_ms", "throughput_kbps", "packet_rate_pkts",
                "mean_rssi_direct", "mean_rssi_relayed"
            ]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"\nWrote detailed CSV summary -> {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
