#!/usr/bin/env python3
"""NR+ Network Visualizer — operator console for the 03_topology experiments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import APP_NAME, APP_VERSION  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="app.py",
        description=f"{APP_NAME} {APP_VERSION} — DECT NR+ three-node topology console",
    )
    parser.add_argument(
        "--ports",
        default="",
        help="Comma-separated transports, e.g. COM9,socket://10.0.0.139:7777",
    )
    parser.add_argument(
        "--connect",
        action="store_true",
        help="Skip the connect dialog and open --ports immediately",
    )
    parser.add_argument(
        "--theme",
        choices=("light", "dark"),
        help="Override the saved theme for this session",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run three simulated boards locally (no hardware needed)",
    )
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args(argv)

    ports = [p.strip() for p in args.ports.split(",") if p.strip()]
    skip_dialog = args.connect and bool(ports)

    network = None
    if args.demo:
        from mock.board import MockNetwork

        network = MockNetwork()
        ports = network.start()
        skip_dialog = True

    if args.theme:
        from core.store import Store

        Store().set("theme", args.theme)

    from ui.main_window import run_app

    try:
        return run_app(preselect=ports or None, skip_connect=skip_dialog)
    finally:
        if network is not None:
            network.stop()


if __name__ == "__main__":
    raise SystemExit(main())
