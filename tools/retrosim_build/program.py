# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Preflight an external Gowin artifact before dispatching the shared programmer."""
import argparse
from pathlib import Path
import subprocess
import sys
from .toolchain import ROOT, Toolchain


def preflight(artifact, report, sdc, sources, *, timing=None):
    artifact, report, sdc = (Path(p).resolve(strict=True) for p in (artifact, report, sdc))
    inputs = {sdc}
    for source in sources:
        source = Path(source).resolve(strict=True)
        if source.is_dir():
            inputs.update(p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in
                          {".sv", ".svh", ".v", ".vh", ".vhd", ".vhdl", ".xdc", ".sdc", ".hex", ".mem", ".mif", ".tcl"})
        else:
            inputs.add(source)
    if not sources:
        raise ValueError("at least one source path is required")
    stale = [p for p in inputs if p.stat().st_mtime_ns > min(artifact.stat().st_mtime_ns, report.stat().st_mtime_ns)]
    if stale:
        raise ValueError("stale bitstream or timing report; rebuild after changing " + ", ".join(map(str, sorted(stale)[:8])))
    timing = timing or (lambda argv: subprocess.run(argv, check=False).returncode)
    if timing([sys.executable, str(ROOT / "tools/timing_signoff.py"), str(report), str(sdc)]):
        raise ValueError("timing sign-off failed; programming refused")
    return artifact


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--sdc", required=True)
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--board", required=True)
    parser.add_argument("--mode", choices=("sram", "flash"), default="sram")
    parser.add_argument("--device", help="expected device; refuse a board mismatch")
    parser.add_argument("--programmer-arg", action="append", default=[])
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        artifact = preflight(args.artifact, args.report, args.sdc, args.source)
        if args.check_only:
            return 0
        tc = Toolchain()
        command = [tc.resolve("BASH_EXE").path, str(ROOT / "tools/gowin_program.sh"),
                   args.board, args.mode, artifact.as_posix(), args.device or "", *args.programmer_arg]
        return subprocess.run(command, env=tc.environment(), check=False).returncode
    except (ValueError, OSError) as error:
        print(f"program: {error}", file=sys.stderr)
        return 1
