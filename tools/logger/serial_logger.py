#!/usr/bin/env python3
"""
Capture Stratus / experiment serial logs and (optionally) drive the Zephyr shell.

  - print live to the terminal
  - save everything to a .txt file
  - type shell commands (same as a serial terminal); they are sent on the UART

Timestamps: each RX (and TX-from-you) line is prefixed with this PC's local wall
clock (datetime.now()), not the board's k_uptime. Use one PC for all boards if
you need comparable host times.

Examples (Windows):
  python serial_logger.py COM5
  python serial_logger.py COM5 --out ../../data/03_topology/run_c.txt
  python serial_logger.py --list
  python serial_logger.py COM5 --no-interact   # log-only (old behaviour)
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Strip Zephyr shell VT/ANSI (colors, cursor moves) so logs stay parseable.
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def clean_line(s: str) -> str:
    s = _ANSI_RE.sub("", s)
    # Shell often reprints prompt mid-line after CSI sequences are removed.
    if "uart:~$" in s:
        s = s.split("uart:~$")[-1]
    return s.strip()

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing dependency: pyserial")
    print("Install with:  python -m pip install -r requirements.txt")
    sys.exit(1)


DEFAULT_BAUD = 115200
REPO_DATA = Path(__file__).resolve().parents[2] / "data" / "01_baseline"


def list_serial_ports() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        print(f"  {p.device:10}  {p.description}  [{p.hwid}]")


def default_log_path() -> Path:
    REPO_DATA.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return REPO_DATA / f"baseline_{stamp}.txt"


def host_ts() -> str:
    """Local PC wall clock, millisecond resolution (timezone = this machine)."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def open_serial(port: str, baud: int, retries: int = 20) -> serial.Serial:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,
            )
            time.sleep(0.3)
            ser.reset_input_buffer()
            return ser
        except serial.SerialException as err:
            last_err = err
            print(f"[{attempt}/{retries}] Waiting for {port}: {err}")
            time.sleep(1.0)
    raise SystemExit(f"Could not open {port}: {last_err}")


def stdin_to_serial(
    ser: serial.Serial,
    logf,
    stop: threading.Event,
    add_timestamp: bool,
) -> None:
    """Forward typed lines to the board (Zephyr shell expects CR or CRLF)."""
    while not stop.is_set():
        try:
            line = sys.stdin.readline()
        except Exception:
            break
        if line == "":
            # EOF (piped input ended)
            break
        payload = line.rstrip("\r\n")
        try:
            ser.write((payload + "\r\n").encode("utf-8", errors="replace"))
            ser.flush()
        except serial.SerialException:
            break

        # Record what you typed with host time (for establishment / command timing)
        if add_timestamp:
            text = f"[{host_ts()}] >>> {payload}"
        else:
            text = f">>> {payload}"
        print(text, flush=True)
        try:
            logf.write(text + "\n")
            logf.flush()
        except ValueError:
            break


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror serial I/O to terminal and save to a .txt file."
    )
    parser.add_argument("port", nargs="?", help="Serial port, e.g. COM5")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--out", type=Path, default=None, help="Output .txt path")
    parser.add_argument("--list", action="store_true", help="List serial ports and exit")
    parser.add_argument(
        "--no-timestamp",
        action="store_true",
        help="Do not prefix each line with a host timestamp",
    )
    parser.add_argument(
        "--no-interact",
        action="store_true",
        help="Log RX only; do not send keyboard input to the board",
    )
    args = parser.parse_args()

    if args.list or not args.port:
        list_serial_ports()
        if not args.port:
            print("\nUsage: python serial_logger.py COM5")
            return 0 if args.list else 1

    out_path = (args.out if args.out is not None else default_log_path()).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    interact = not args.no_interact
    add_ts = not args.no_timestamp

    print(f"Port       : {args.port}")
    print(f"Baud       : {args.baud}")
    print(f"Log file   : {out_path}")
    print(f"Host clock : {datetime.now().astimezone().tzname()} "
          f"(local wall time on this PC)")
    print(f"Interactive: {'yes — type exp commands, Enter to send' if interact else 'no'}")
    print("Ctrl+C to stop.\n")

    ser = open_serial(args.port, args.baud)
    buffer = bytearray()
    stop = threading.Event()
    writer: threading.Thread | None = None

    try:
        with out_path.open("a", encoding="utf-8", errors="replace", newline="") as logf:
            header = (
                f"===== serial capture start "
                f"{datetime.now().isoformat(timespec='seconds')} "
                f"port={args.port} baud={args.baud} interact={interact} =====\n"
            )
            logf.write(header)
            logf.flush()
            print(header, end="")

            if interact:
                writer = threading.Thread(
                    target=stdin_to_serial,
                    args=(ser, logf, stop, add_ts),
                    name="stdin_uart",
                    daemon=True,
                )
                writer.start()

            while True:
                chunk = ser.read(256)
                if not chunk:
                    continue

                buffer.extend(chunk)

                while True:
                    nl = buffer.find(b"\n")
                    if nl < 0:
                        break
                    raw = bytes(buffer[: nl + 1])
                    del buffer[: nl + 1]

                    line = clean_line(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
                    if not line:
                        continue
                    if add_ts:
                        text = f"[{host_ts()}] {line}"
                    else:
                        text = line

                    print(text, flush=True)
                    logf.write(text + "\n")
                    logf.flush()

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        stop.set()
        if ser.is_open:
            ser.close()
        print(f"Saved: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
