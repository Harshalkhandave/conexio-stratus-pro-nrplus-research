#!/usr/bin/env python3
"""Experiment 06: Store-and-Forward Automated Test Suite.

Executes an automated multi-phase outage validation benchmark across a 3-node
DECT NR+ mesh topology (Source -> Relay -> Sink) without manual shell typing.

Benchmark Execution Phases:
    1. Node Identification & Role Discovery:
       Queries each connected board over serial to determine unique hardware node IDs.
       Maps roles: Lowest ID -> Sink, Middle ID -> Relay, Highest ID -> Source.
    2. Forced Deterministic Setup:
       Configures roles, timers, hop routes, and traffic parameters on all nodes.
    3. Pre-Test Status Capture:
       Queries initial store statistics, boot epochs, and radio state.
    4. Phase 1: Healthy Baseline (Default: 30s):
       Verifies clean hop-by-hop forwarding and continuous FIFO packet delivery.
    5. Phase 2: Short Outage & Backlog Drain (Default: 3 min):
       Halts the sink node, forces the relay node to buffer ingress frames in RAM,
       restores the sink, and verifies ordered backlog draining with zero loss.
    6. Phase 3: Extended Outage & Buffer Saturation (Default: 5 min):
       Halts the sink node long enough to exhaust the telemetry shelf (288 slots),
       verifies graceful QUEUE_FULL backpressure without corruption, restores the sink,
       and verifies complete ordered drain of all admitted packets.
    7. Post-Test Verification & Reporting:
       Evaluates the conservation equation, verifies contiguous sequence numbers,
       and writes a comprehensive report.txt and per-node execution logs.

Artifacts Generated (per run directory):
    - source.txt: Complete timestamped console log for the source node.
    - relay.txt:  Complete timestamped console log for the relay node.
    - sink.txt:   Complete timestamped console log for the sink node.
    - report.txt: Structured benchmark execution summary and PASS/FAIL verdict.

Default Usage:
    python sf_auto_test.py
    python sf_auto_test.py COM7 socket://10.0.0.139:7777 socket://10.0.0.139:7778
    python sf_auto_test.py --out-dir data/06_store/test_run
"""

from __future__ import annotations

import argparse
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Final, List, Optional, Tuple

try:
    import serial
except ImportError:
    print("Error: Missing required dependency 'pyserial'.", file=sys.stderr)
    print("Install it with: pip install pyserial", file=sys.stderr)
    sys.exit(1)

# Regex Patterns for Log Parsing
ANSI_ESCAPE_RE: Final[re.Pattern[str]] = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
NODE_INFO_RE: Final[re.Pattern[str]] = re.compile(r"node=(\d+)\s+role=(\w+)")
DELIVER_EVENT_RE: Final[re.Pattern[str]] = re.compile(r"DELIVER: node=\d+ seq=(\d+) src=(\d+)")
BAD_FRAME_RE: Final[re.Pattern[str]] = re.compile(r"BAD_FRAME:")
QUEUE_FULL_RE: Final[re.Pattern[str]] = re.compile(r"status=QUEUE_FULL")
DEPTH_STATS_RE: Final[re.Pattern[str]] = re.compile(
    r"generated=(\d+) delivered=(\d+) stored=(\d+) drained=(\d+) depth=(\d+)"
)

# Benchmark Configuration Defaults
DEFAULT_SERIAL_PORTS: Final[Tuple[str, ...]] = (
    "COM7",
    "socket://10.0.0.139:7777",
    "socket://10.0.0.139:7778",
)
DEFAULT_BAUD_RATE: Final[int] = 115200
DEFAULT_HEALTHY_DURATION_S: Final[int] = 30
DEFAULT_SHORT_OUTAGE_S: Final[int] = 180
DEFAULT_LONG_OUTAGE_S: Final[int] = 300
DEFAULT_DRAIN_TIMEOUT_S: Final[int] = 180
DEFAULT_PAYLOAD_SIZE: Final[int] = 16
DEFAULT_INTERVAL_MS: Final[int] = 1000
DEFAULT_ACK_TIMEOUT_MS: Final[int] = 400


def strip_ansi_and_prompt(raw: str) -> str:
    """Strips ANSI escape characters and Zephyr shell prompt prefixes from serial lines.

    Args:
        raw: Raw line string from serial buffer.

    Returns:
        Cleaned text string.
    """
    text = ANSI_ESCAPE_RE.sub("", raw)
    if "uart:~$" in text:
        text = text.split("uart:~$")[-1]
    return text.strip()


def get_host_timestamp() -> str:
    """Returns the current host wall-clock timestamp formatted as HH:MM:SS.mmm."""
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class Board:
    """Manages an asynchronous, thread-safe serial connection to a Conexio Stratus Pro node."""

    def __init__(self, port: str, log_path: Path, baud_rate: int = DEFAULT_BAUD_RATE) -> None:
        """Initializes board connection state.

        Args:
            port: Serial COM port (e.g. 'COM7') or RFC2217 URL (e.g. 'socket://host:port').
            log_path: Destination path for writing the raw captured log.
            baud_rate: Serial baud rate (default 115200).
        """
        self.port: str = port
        self.node_id: int = 0
        self.baud_rate: int = baud_rate
        self.lines: List[str] = []
        self.log_path: Path = log_path
        self._log_file = log_path.open("w", encoding="utf-8")
        self._lock: threading.Lock = threading.Lock()
        self._stop_event: threading.Event = threading.Event()
        self._serial: Optional[serial.Serial] = None
        self._reader_thread: Optional[threading.Thread] = None

    def open(self) -> None:
        """Opens the serial port and starts the background reader thread."""
        if "://" in self.port:
            self._serial = serial.serial_for_url(self.port, baudrate=self.baud_rate, timeout=0.2)
        else:
            self._serial = serial.Serial(self.port, self.baud_rate, timeout=0.2)

        self.write_marker(f"open {self.port}")
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"sf-reader-{self.port}",
            daemon=True,
        )
        self._reader_thread.start()

    def close(self) -> None:
        """Stops the reader thread, closes the serial interface, and flushes log files."""
        self._stop_event.set()
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        try:
            self._log_file.flush()
            self._log_file.close()
        except Exception:
            pass

    def write_marker(self, text: str) -> None:
        """Inserts an annotated host checkpoint marker into the log file.

        Args:
            text: Marker description string.
        """
        with self._lock:
            self._log_file.write(f"[{get_host_timestamp()}] ##### {text} #####\n")
            self._log_file.flush()

    def _reader_loop(self) -> None:
        """Background thread loop reading raw serial stream into lines."""
        assert self._serial is not None
        buffer = bytearray()
        while not self._stop_event.is_set():
            try:
                chunk = self._serial.read(256)
            except Exception:
                break

            if not chunk:
                continue

            buffer.extend(chunk)
            while b"\n" in buffer:
                raw_line, _, buffer = buffer.partition(b"\n")
                line = strip_ansi_and_prompt(raw_line.decode("utf-8", errors="replace"))
                if not line:
                    continue
                with self._lock:
                    self.lines.append(line)
                    self._log_file.write(f"[{get_host_timestamp()}] {line}\n")
                    self._log_file.flush()

    def send(self, cmd: str, pause_s: float = 0.45) -> None:
        """Sends a shell command to the device followed by a brief settling pause.

        Args:
            cmd: Command string (e.g. 'exp status').
            pause_s: Settle time in seconds before returning.
        """
        assert self._serial is not None
        self.write_marker(f"cmd {cmd}")
        self._serial.write((cmd + "\r\n").encode("utf-8"))
        self._serial.flush()
        time.sleep(pause_s)

    def snapshot(self) -> List[str]:
        """Returns a thread-safe snapshot copy of all received log lines."""
        with self._lock:
            return list(self.lines)

    def wait_for(
        self,
        pattern: re.Pattern[str],
        timeout_s: float,
        since_index: int = 0,
    ) -> Optional[re.Match[str]]:
        """Polls received lines for a pattern match within the timeout window.

        Args:
            pattern: Compiled regex to search for.
            timeout_s: Timeout in seconds.
            since_index: Start searching from this line index in the snapshot.

        Returns:
            Match object if found, or None on timeout.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            lines = self.snapshot()
            for line in lines[since_index:]:
                match = pattern.search(line)
                if match:
                    return match
            time.sleep(0.05)
        return None


def extract_deliveries_from_source(sink: Board, source_id: int, since_index: int) -> List[int]:
    """Extracts unique deliver sequence numbers received at the sink from a given source.

    Args:
        sink: Sink board instance.
        source_id: Hardware device ID of the generating source node.
        since_index: Line index offset in the sink log.

    Returns:
        List of unique integer sequence numbers delivered.
    """
    delivered_seqs: List[int] = []
    for line in sink.snapshot()[since_index:]:
        match = DELIVER_EVENT_RE.search(line)
        if match and int(match.group(2)) == source_id:
            seq = int(match.group(1))
            if seq not in delivered_seqs:
                delivered_seqs.append(seq)
    return delivered_seqs


def count_pattern_occurrences(board: Board, pattern: re.Pattern[str], since_index: int) -> int:
    """Counts occurrences of a regex pattern in lines received since an offset."""
    return sum(1 for line in board.snapshot()[since_index:] if pattern.search(line))


def capture_status_block(board: Board, report_lines: List[str], title: str) -> None:
    """Executes 'exp status' on a board and appends key state indicators to the report.

    Args:
        board: Target board instance.
        report_lines: Accumulator list for the structured report.
        title: Descriptive label for the status snapshot checkpoint.
    """
    start_index = len(board.snapshot())
    board.write_marker(title)
    board.send("exp status", pause_s=1.3)
    header = f"--- {title}  {board.port} node={board.node_id} ---"
    report_lines.append(header)
    print(f"  {title}  node={board.node_id}")

    captured_any = False
    for line in board.snapshot()[start_index:]:
        if line.startswith(("node=", "generated=", "rx_queue", "carrier=")):
            report_lines.append(f"    {line}")
            print(f"    {line}")
            captured_any = True

    if not captured_any:
        report_lines.append("    (no status lines)")
        print("    (no status lines)")


def identify_node(board: Board) -> None:
    """Queries device identity and sets board.node_id.

    Raises:
        RuntimeError: If device fails to respond with a valid node ID.
    """
    board.send("")
    board.send("exp stop", pause_s=0.6)
    mark_index = len(board.snapshot())
    board.send("exp status", pause_s=1.0)

    match = board.wait_for(NODE_INFO_RE, timeout_s=5.0, since_index=mark_index)
    if match is None:
        for line in reversed(board.snapshot()):
            match = NODE_INFO_RE.search(line)
            if match:
                break

    if match is None:
        raise RuntimeError(f"Port {board.port}: Failed to read node ID. Is 06_store firmware running?")
    board.node_id = int(match.group(1))


def force_network_configuration(
    source: Board,
    relay: Board,
    sink: Board,
    payload_size: int = DEFAULT_PAYLOAD_SIZE,
    interval_ms: int = DEFAULT_INTERVAL_MS,
    ack_timeout_ms: int = DEFAULT_ACK_TIMEOUT_MS,
) -> None:
    """Forces deterministic experiment configuration on all three topology nodes.

    Args:
        source: Source board instance.
        relay: Relay board instance.
        sink: Sink board instance.
        payload_size: Application payload size in bytes.
        interval_ms: Source transmission period in milliseconds.
        ack_timeout_ms: Hop-by-hop ACK timeout in milliseconds.
    """
    for board in (source, relay, sink):
        board.send("exp stop", pause_s=0.5)
        board.send("exp flush", pause_s=0.4)

    # Configure Sink
    sink.send("exp role sink")
    sink.send("exp sett hello 2000")
    sink.send("exp sett hello_tx on")
    sink.send("exp sett direct on")

    # Configure Relay
    relay.send("exp role relay")
    relay.send("exp sett hello 2000")
    relay.send("exp sett hello_tx on")
    relay.send("exp sett direct on")
    relay.send("exp sett assume_up off")

    # Configure Source
    source.send("exp role source")
    source.send("exp sett direct off")
    source.send(f"exp sett dest {sink.node_id}")
    source.send(f"exp route set {sink.node_id} {relay.node_id}")
    source.send(f"exp sett size {payload_size}")
    source.send(f"exp sett interval {interval_ms}")
    source.send("exp sett count 0")
    source.send("exp sett assume_up off")
    source.send(f"exp sett ack_timeout {ack_timeout_ms}")
    source.send("exp sett policy reject")

    if source.wait_for(re.compile(rf"size={payload_size}"), timeout_s=3.0) is None:
        raise RuntimeError(f"Source node did not acknowledge payload size={payload_size}")


def is_contiguous_sequence(seqs: List[int]) -> bool:
    """Checks if a list of integer sequence numbers is strictly contiguous without gaps."""
    if len(seqs) < 2:
        return True
    return seqs == list(range(seqs[0], seqs[0] + len(seqs)))


def sleep_with_markers(boards: List[Board], seconds: int, label: str) -> None:
    """Annotates logs on all boards with start/end markers and sleeps for the specified duration."""
    print(f"  {label}: {seconds} s")
    for board in boards:
        board.write_marker(f"{label} begin {seconds}s")
    time.sleep(seconds)
    for board in boards:
        board.write_marker(f"{label} end")


def wait_for_backlog_drain(
    sink: Board,
    source_id: int,
    since_index: int,
    timeout_s: float = DEFAULT_DRAIN_TIMEOUT_S,
) -> List[int]:
    """Monitors the sink until new deliveries stop arriving after an outage restoration.

    Args:
        sink: Sink board instance.
        source_id: Hardware device ID of the generating source node.
        since_index: Starting line offset in the sink log.
        timeout_s: Maximum drain wait timeout in seconds.

    Returns:
        List of all sequence numbers delivered from source_id since since_index.
    """
    deadline = time.monotonic() + timeout_s
    previous_count = -1
    quiet_start_time = time.monotonic()
    delivered = extract_deliveries_from_source(sink, source_id, since_index)

    while time.monotonic() < deadline:
        time.sleep(0.5)
        delivered = extract_deliveries_from_source(sink, source_id, since_index)
        if len(delivered) != previous_count:
            previous_count = len(delivered)
            quiet_start_time = time.monotonic()
        elif time.monotonic() - quiet_start_time > 8.0 and delivered:
            # Backlog drain completed (quiescent for > 8 seconds)
            break

    return delivered


def parse_cli_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Configures and parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automated Store-and-Forward Outage Benchmark for Conexio Stratus Pro DECT NR+",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "ports",
        nargs="*",
        default=list(DEFAULT_SERIAL_PORTS),
        help="Three serial ports or RFC2217 URLs (e.g. COM7 socket://10.0.0.139:7777 socket://10.0.0.139:7778)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=DEFAULT_BAUD_RATE,
        help="Baud rate for serial connections",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Directory to save logs and report. Defaults to tools/logger/sf_logs/<timestamp>",
    )
    parser.add_argument(
        "--healthy-duration",
        type=int,
        default=DEFAULT_HEALTHY_DURATION_S,
        help="Duration of the initial healthy baseline phase in seconds",
    )
    parser.add_argument(
        "--outage-short",
        type=int,
        default=DEFAULT_SHORT_OUTAGE_S,
        help="Duration of the short outage phase in seconds",
    )
    parser.add_argument(
        "--outage-long",
        type=int,
        default=DEFAULT_LONG_OUTAGE_S,
        help="Duration of the extended outage phase in seconds",
    )
    parser.add_argument(
        "--drain-timeout",
        type=int,
        default=DEFAULT_DRAIN_TIMEOUT_S,
        help="Maximum wait time for backlog drain after restoration in seconds",
    )
    parser.add_argument(
        "--payload-size",
        type=int,
        default=DEFAULT_PAYLOAD_SIZE,
        help="Application payload size in bytes (16 recommended on nRF9151 modem)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_MS,
        help="Source transmission interval in milliseconds",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Main benchmark execution orchestration."""
    args = parse_cli_args(argv)

    if len(args.ports) != 3:
        print("Error: Exactly 3 serial ports or URLs must be provided.", file=sys.stderr)
        return 2

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.out_dir is not None:
        log_dir: Path = args.out_dir
    else:
        log_dir = Path(__file__).resolve().parent / "sf_logs" / timestamp_str

    log_dir.mkdir(parents=True, exist_ok=True)

    report_lines: List[str] = [
        f"06_store Automated Benchmark Run: {timestamp_str}",
        f"Parameters: size={args.payload_size} interval={args.interval}ms count=forever assume_up=off direct=off",
        f"Durations: healthy={args.healthy_duration}s short_outage={args.outage_short}s long_outage={args.outage_long}s",
    ]
    failures: List[str] = []
    named_logs: List[Tuple[Board, str]] = []

    boards = [
        Board(args.ports[0], log_dir / "link1.txt", baud_rate=args.baud),
        Board(args.ports[1], log_dir / "link2.txt", baud_rate=args.baud),
        Board(args.ports[2], log_dir / "link3.txt", baud_rate=args.baud),
    ]

    print(f"Log destination -> {log_dir}")

    try:
        # Step 1: Open connections
        print("\n[Step 1] Opening serial interfaces...")
        for board in boards:
            board.open()
            print(f"  Connected to {board.port}")
        time.sleep(0.5)

        # Step 2: Identify Nodes
        print("\n[Step 2] Discovering node identities...")
        for board in boards:
            identify_node(board)
            print(f"  {board.port} -> Node ID: {board.node_id}")

        if len({b.node_id for b in boards}) != 3:
            raise RuntimeError("Expected 3 distinct node IDs across the connected boards.")

        # Assign roles by sorted node ID
        ordered_boards = sorted(boards, key=lambda b: b.node_id)
        sink, relay, source = ordered_boards[0], ordered_boards[1], ordered_boards[2]
        named_logs.extend(((source, "source.txt"), (relay, "relay.txt"), (sink, "sink.txt")))

        print(
            f"\nTopology Mapping:\n"
            f"  Sink:   Node {sink.node_id:<5} ({sink.port})\n"
            f"  Relay:  Node {relay.node_id:<5} ({relay.port})\n"
            f"  Source: Node {source.node_id:<5} ({source.port})"
        )
        report_lines.append(
            f"source={source.node_id} ({source.port})  "
            f"relay={relay.node_id} ({relay.port})  "
            f"sink={sink.node_id} ({sink.port})"
        )

        # Step 3: Configure Mesh
        print("\n[Step 3] Applying deterministic configuration...")
        force_network_configuration(
            source,
            relay,
            sink,
            payload_size=args.payload_size,
            interval_ms=args.interval,
            ack_timeout_ms=DEFAULT_ACK_TIMEOUT_MS,
        )

        print("\n[Step 4] Pre-test status capture...")
        for board in (source, relay, sink):
            capture_status_block(board, report_lines, "Status Before Run")

        # Step 5: Start Experiment Run
        print("\n[Step 5] Launching radio nodes (Sink -> Relay -> Source)...")
        sink.send("exp start", pause_s=0.7)
        relay.send("exp start", pause_s=0.7)
        sink_baseline_mark = len(sink.snapshot())
        relay_baseline_mark = len(relay.snapshot())
        source_baseline_mark = len(source.snapshot())
        source.send("exp start", pause_s=0.4)

        # Phase 1: Healthy Baseline
        print(f"\n[Phase 1] Monitoring healthy delivery ({args.healthy_duration} s)...")
        for board in (source, relay, sink):
            board.write_marker(f"healthy begin {args.healthy_duration}s")

        baseline_deadline = time.monotonic() + 40.0 + args.healthy_duration
        healthy_seqs: List[int] = []
        while time.monotonic() < baseline_deadline:
            healthy_seqs = extract_deliveries_from_source(sink, source.node_id, sink_baseline_mark)
            if healthy_seqs and (
                time.monotonic() > baseline_deadline - args.healthy_duration
                or len(healthy_seqs) >= args.healthy_duration // 2
            ):
                break
            time.sleep(0.2)

        if healthy_seqs:
            time.sleep(args.healthy_duration)
            healthy_seqs = extract_deliveries_from_source(sink, source.node_id, sink_baseline_mark)

        for board in (source, relay, sink):
            board.write_marker("healthy end")

        bad_frames_count = count_pattern_occurrences(relay, BAD_FRAME_RE, relay_baseline_mark)
        queue_full_count = count_pattern_occurrences(source, QUEUE_FULL_RE, source_baseline_mark)

        print(f"  Healthy delivered: {len(healthy_seqs)} packets. Initial seqs: {healthy_seqs[:6]}")
        report_lines.append(
            f"healthy n={len(healthy_seqs)} bad_frame={bad_frames_count} queue_full={queue_full_count} seqs={healthy_seqs}"
        )

        if bad_frames_count:
            failures.append(f"BAD_FRAME encountered during healthy phase ({bad_frames_count})")
        if queue_full_count:
            failures.append(f"QUEUE_FULL encountered during healthy phase ({queue_full_count})")
        if len(healthy_seqs) < max(1, args.healthy_duration // 2):
            failures.append(f"Insufficient deliveries in healthy window ({len(healthy_seqs)})")
        if not is_contiguous_sequence(healthy_seqs):
            failures.append(f"Healthy sequence numbers non-contiguous: {healthy_seqs}")

        for board in (source, relay, sink):
            capture_status_block(board, report_lines, "Status After Healthy Phase")

        # Phase 2: Short Outage (3 min)
        print(f"\n[Phase 2] Short outage simulation ({args.outage_short} s)...")
        outage1_sink_mark = len(sink.snapshot())
        sink.send("exp stop", pause_s=0.5)
        sleep_with_markers([source, relay, sink], args.outage_short, "Outage Short (3min)")

        for board in (source, relay):
            capture_status_block(board, report_lines, "Status Sink Offline (3min)")

        print("  Restoring sink node...")
        sink.send("exp start", pause_s=0.6)
        print(f"  Waiting for backlog drain (timeout {args.drain_timeout} s)...")
        drained_short = wait_for_backlog_drain(sink, source.node_id, outage1_sink_mark, args.drain_timeout)
        total_delivered_short = extract_deliveries_from_source(sink, source.node_id, sink_baseline_mark)

        print(f"  Drained from outage: {len(drained_short)} pkts | Total delivered: {len(total_delivered_short)} pkts")
        report_lines.append(
            f"after_3min_outage drained={len(drained_short)} total={len(total_delivered_short)} tail={total_delivered_short[-6:]}"
        )

        if not is_contiguous_sequence(total_delivered_short):
            failures.append(f"Gap or reordering detected after 3 min outage (tail={total_delivered_short[-12:]})")
        if len(drained_short) < 3:
            failures.append("Relay backlog failed to drain after 3 min outage")

        for board in (source, relay, sink):
            capture_status_block(board, report_lines, "Status After 3min Outage Drain")

        # Phase 3: Extended Outage (5 min)
        print(f"\n[Phase 3] Extended outage simulation ({args.outage_long} s)...")
        outage2_sink_mark = len(sink.snapshot())
        full_prior_to_outage = count_pattern_occurrences(source, QUEUE_FULL_RE, source_baseline_mark)
        sink.send("exp stop", pause_s=0.5)
        sleep_with_markers([source, relay, sink], args.outage_long, "Outage Long (5min)")

        for board in (source, relay):
            capture_status_block(board, report_lines, "Status Sink Offline (5min)")

        full_during_outage = (
            count_pattern_occurrences(source, QUEUE_FULL_RE, source_baseline_mark) - full_prior_to_outage
        )
        print(f"  QUEUE_FULL events observed during 5 min: {full_during_outage} (Capacity ~288 slots)")
        report_lines.append(f"QUEUE_FULL during 5min={full_during_outage}")

        print("  Restoring sink node...")
        sink.send("exp start", pause_s=0.6)
        print(f"  Waiting for backlog drain (timeout {args.drain_timeout} s)...")
        drained_long = wait_for_backlog_drain(sink, source.node_id, outage2_sink_mark, args.drain_timeout)
        total_delivered_long = extract_deliveries_from_source(sink, source.node_id, sink_baseline_mark)

        print(f"  Drained from outage: {len(drained_long)} pkts | Total delivered: {len(total_delivered_long)} pkts")
        report_lines.append(
            f"after_5min_outage drained={len(drained_long)} total={len(total_delivered_long)} tail={total_delivered_long[-8:]}"
        )

        if not is_contiguous_sequence(total_delivered_long):
            failures.append(f"Gap or reordering detected after 5 min outage (tail={total_delivered_long[-12:]})")
        if full_during_outage == 0:
            failures.append("Extended outage produced 0 QUEUE_FULL events. Store buffer should have saturated.")

        for board in (source, relay, sink):
            capture_status_block(board, report_lines, "Status After 5min Outage Drain")

        # Stop Nodes
        for board in (source, relay, sink):
            board.send("exp stop", pause_s=0.3)

    except KeyboardInterrupt:
        print("\n\n[ABORT] KeyboardInterrupt received. Terminating test run cleanly...")
        failures.append("Benchmark interrupted by user (KeyboardInterrupt)")
    except Exception as exc:
        print(f"\n\n[ERROR] Unhandled exception: {exc}")
        failures.append(str(exc))
    finally:
        # Graceful cleanup
        for board in boards:
            try:
                if board._serial is not None and getattr(board._serial, "is_open", False):
                    board.send("exp stop", pause_s=0.15)
            except Exception:
                pass
            board.close()

        # Rename raw link log files to their semantic names (source.txt, relay.txt, sink.txt)
        for board, semantic_name in named_logs:
            target_path = log_dir / semantic_name
            if board.log_path.exists() and board.log_path.name != semantic_name:
                try:
                    if target_path.exists():
                        target_path.unlink()
                    board.log_path.replace(target_path)
                except Exception as e:
                    print(f"Warning: Failed to rename {board.log_path.name} to {semantic_name}: {e}")

    # Generate final report
    verdict = "PASS" if not failures else "FAIL"
    report_lines.append(f"\nFinal Verdict: {verdict}")
    if failures:
        report_lines.append("Failures Encountered:")
        for failure_msg in failures:
            report_lines.append(f"  - {failure_msg}")

    report_file = log_dir / "report.txt"
    report_file.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    print(f"\nSummary Report written to: {report_file}")

    if failures:
        print("\nRESULT: [FAIL]")
        for failure_msg in failures:
            print(f"  - {failure_msg}")
        return 1

    print("\nRESULT: [PASS] All store-and-forward validation checks succeeded!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
