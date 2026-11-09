#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Open a UART first, run a programmer, and judge post-load output.

FPGA configuration is often the board's reset, so opening the console after
the programmer exits loses the only boot banner.  Opening it first has its own
trap: USB serial drivers can deliver bytes buffered from the previously loaded
image.  This tool handles both cases without knowing anything about a specific
board or diagnostic:

  * open the UART before starting the caller-supplied programming command;
  * preserve and report the programmer's return code;
  * discard UART bytes before an optional post-load marker;
  * capture for a bounded time after programming completes; and
  * require any number of exact verdict strings.

Example, from hh-sdcard:

  python3 ../retrosim-build/tools/uart_prog_capture.py \
    --port COM255 --timeout 90 --marker "SD(4-bit)" \
    --expect "P=1 E=0 EC=0" --expect "MV=1" \
    --expect "STR n=32768" --expect "ok=1 errs=00000 e=0c0" \
    --log fpga/impl_hh_sdcard_a7lite_sd4_diag/uart.log \
    --cwd fpga -- "C:/Program Files/Git/bin/bash.exe" \
    build.sh a7lite sd4 prog

Requires pyserial (``python3 -m pip install pyserial``).  With no programming
command, the tool opens the UART and judges the already-running image.

A port that a serbridge started with ``--listen`` holds is opened through the
bridge over RFC 2217 (``bridgeport.py`` beside this script), so the bridge's
log keeps the whole capture and other tools can watch the line; with no bridge
the port is opened directly.
"""

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


class PostMarkerCapture:
    """Retain bytes starting at a marker, including split-marker handling."""

    def __init__(self, marker, strip_bit7=False):
        self.marker = marker.encode("latin-1") if marker else None
        self.strip_bit7 = strip_bit7
        self.marker_seen = self.marker is None
        self.pending = bytearray()
        self.judged = bytearray()
        self.discarded = 0

    def feed(self, data):
        """Consume bytes and return newly accepted post-marker bytes."""
        if self.strip_bit7:
            data = bytes(value & 0x7F for value in data)
        if self.marker_seen:
            self.judged.extend(data)
            return data

        self.pending.extend(data)
        index = self.pending.find(self.marker)
        if index >= 0:
            accepted = bytes(self.pending[index:])
            self.discarded += index
            self.pending.clear()
            self.marker_seen = True
            self.judged.extend(accepted)
            return accepted

        # Only this suffix can participate in a marker split across reads.
        keep = max(len(self.marker) - 1, 0)
        if len(self.pending) > keep:
            count = len(self.pending) - keep
            self.discarded += count
            del self.pending[:count]
        return b""

    def text(self):
        return self.judged.decode("latin-1", errors="replace")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Open UART before programming and judge post-load output.")
    parser.add_argument("--port", required=True, help="serial port, e.g. COM255")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument(
        "--timeout", type=float, default=30.0,
        help="capture seconds after the programmer exits (default: 30)")
    parser.add_argument(
        "--settle", type=float, default=0.5,
        help="extra capture after all required strings appear (default: 0.5)")
    parser.add_argument(
        "--marker",
        help="discard stale input until this exact post-load string appears")
    parser.add_argument(
        "--expect", action="append", default=[], metavar="TEXT",
        help="exact required post-marker string; repeat for multiple checks")
    parser.add_argument(
        "--log", type=Path,
        help="write accepted post-marker UART bytes to this file")
    parser.add_argument(
        "--cwd", type=Path,
        help="working directory for the programming command")
    parser.add_argument(
        "--strip-bit7", action="store_true",
        help="clear the high bit of each UART byte before matching/output")
    parser.add_argument(
        "program", nargs=argparse.REMAINDER,
        help="programming command after --; omit to capture the running image")
    args = parser.parse_args(argv)
    if args.program and args.program[0] == "--":
        args.program = args.program[1:]
    if args.timeout < 0 or args.settle < 0:
        parser.error("--timeout and --settle must be non-negative")
    if args.marker == "":
        parser.error("--marker must not be empty")
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        import serial
    except ImportError:
        print("uart_prog_capture: pyserial is required; install it with\n"
              "  python3 -m pip install pyserial", file=sys.stderr)
        return 2
    # bridgeport.py sits beside this script (a copy of
    # retrosim-transports/serbridge/clients/python/bridgeport.py).
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import bridgeport
    required_api = ("Serial", "serial_for_url", "SerialException", "EIGHTBITS",
                    "PARITY_NONE", "STOPBITS_ONE")
    if any(not hasattr(serial, name) for name in required_api):
        print("uart_prog_capture: the imported 'serial' module is not "
              "pyserial; remove the conflicting package and install with\n"
              "  python3 -m pip install pyserial", file=sys.stderr)
        return 2

    cwd = args.cwd.resolve() if args.cwd else None
    if cwd and not cwd.is_dir():
        print(f"uart_prog_capture: --cwd is not a directory: {cwd}",
              file=sys.stderr)
        return 2

    log_file = None
    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        log_file = args.log.open("wb")

    capture = PostMarkerCapture(args.marker, args.strip_bit7)
    process = None
    program_rc = 0
    post_deadline = None
    satisfied_at = None

    try:
        try:
            # Through the serbridge holding the port when one does, else
            # directly. dtr/rts are applied before the port opens: some
            # targets wire DTR/RTS to reset, so the common ``Serial(port,
            # ...)`` shorthand can perturb the board before the programmer
            # supplies the intended reset.
            uart = bridgeport.open_port(
                args.port, args.baud,
                bytesize=serial.EIGHTBITS, parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE, timeout=0.05,
                xonxoff=False, rtscts=False, dsrdtr=False,
                dtr=False, rts=False)
        except (serial.SerialException, OSError, ValueError) as exc:
            print(f"uart_prog_capture: cannot open {args.port}: {exc}\n"
                  "A stale Python process may still own the port.",
                  file=sys.stderr)
            return 2

        with uart:
            print(f"[uart] opened {args.port} at {args.baud} 8N1 before "
                  "programming", file=sys.stderr)
            if args.program:
                rendered = shlex.join(args.program)
                print(f"[prog] {rendered}", file=sys.stderr)
                if cwd:
                    print(f"[prog] cwd={cwd}", file=sys.stderr)
                try:
                    process = subprocess.Popen(
                        args.program, cwd=os.fspath(cwd) if cwd else None,
                        stdout=sys.stderr, stderr=sys.stderr)
                except OSError as exc:
                    print(f"uart_prog_capture: cannot start programmer: {exc}",
                          file=sys.stderr)
                    return 2
            else:
                print("[prog] no command; capturing the running image",
                      file=sys.stderr)
                post_deadline = time.monotonic() + args.timeout

            while True:
                data = uart.read(4096)
                if data:
                    marker_was_seen = capture.marker_seen
                    accepted = capture.feed(data)
                    if not marker_was_seen and capture.marker_seen:
                        print(f"[uart] marker matched; discarded "
                              f"{capture.discarded} stale byte(s)",
                              file=sys.stderr)
                    if accepted:
                        sys.stdout.buffer.write(accepted)
                        sys.stdout.buffer.flush()
                        if log_file:
                            log_file.write(accepted)
                            log_file.flush()

                now = time.monotonic()
                if process is not None and process.poll() is not None:
                    program_rc = process.returncode
                    print(f"[prog] exit {program_rc}", file=sys.stderr)
                    process = None
                    post_deadline = now + args.timeout
                    if program_rc != 0:
                        break

                missing = [item for item in args.expect
                           if item not in capture.text()]
                conditions_requested = bool(args.marker or args.expect)
                conditions_met = capture.marker_seen and not missing
                if (post_deadline is not None and conditions_requested
                        and conditions_met):
                    if satisfied_at is None:
                        satisfied_at = now
                    if now - satisfied_at >= args.settle:
                        break

                if post_deadline is not None and now >= post_deadline:
                    break

        missing = [item for item in args.expect if item not in capture.text()]
        if program_rc != 0:
            print(f"uart_prog_capture: programmer failed with exit "
                  f"{program_rc}", file=sys.stderr)
            return program_rc if 0 < program_rc < 256 else 1
        if args.marker and not capture.marker_seen:
            print(f"uart_prog_capture: marker not seen: {args.marker!r}",
                  file=sys.stderr)
            return 1
        if missing:
            print("uart_prog_capture: missing required UART text:",
                  file=sys.stderr)
            for item in missing:
                print(f"  {item!r}", file=sys.stderr)
            return 1
        print("[uart] capture PASS", file=sys.stderr)
        return 0
    except KeyboardInterrupt:
        print("\nuart_prog_capture: interrupted", file=sys.stderr)
        return 130
    finally:
        if process is not None and process.poll() is None:
            print("uart_prog_capture: programmer is still running; it was not "
                  "terminated during cleanup", file=sys.stderr)
        if log_file:
            log_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
