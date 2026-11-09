# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Merge explicitly selected coverage data; stale directory entries never join."""
from pathlib import Path
import shutil
import sys
from .process import run
from .toolchain import Toolchain


def merge(inputs, output, *, cwd, summary=None, annotate=True, groups=None, timeout=300, tc=None):
    tc = tc or Toolchain()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = [Path(p).resolve(strict=True) for p in inputs]
    if not files or any(not path.is_file() or not path.stat().st_size for path in files):
        raise ValueError("coverage merge requires nonempty data files from this run")
    tool = tc.resolve("VERILATOR_COVERAGE").path
    selections = {"merged": files}
    for name, members in (groups or {}).items():
        if not name or not all(char.isalnum() or char in "_-" for char in name):
            raise ValueError("invalid coverage group name")
        members = [Path(p).resolve(strict=True) for p in members]
        if not members or not set(members).issubset(files):
            raise ValueError("coverage group contains inputs outside this run")
        selections["merged_" + name] = members
    for name, members in selections.items():
        destination = output / (name + ".dat")
        destination.unlink(missing_ok=True)
        result = run([tool, "--write", str(destination), *map(str, members)], cwd=cwd,
                     log=output / (name + ".log"), env=tc.environment(), timeout=timeout)
        if not result.passed() or not destination.is_file(): return 1
    merged = output / "merged.dat"
    if annotate:
        annotation = output / "annotate"
        if annotation.resolve() != output / "annotate":
            raise ValueError("annotation directory escapes the coverage output")
        if annotation.is_dir():
            shutil.rmtree(annotation)
        result = run([tool, "--annotate", str(annotation), "--annotate-min", "1", str(merged)],
                     cwd=cwd, log=output / "annotate.log", env=tc.environment(), timeout=timeout)
        if not result.passed(): return 1
    if summary:
        result = run([sys.executable, str(Path(summary).resolve()), str(merged)], cwd=cwd,
                     log=output / "summary.log", env=tc.environment(), timeout=timeout)
        print(result.log.read_text(encoding="utf-8", errors="replace"))
        if not result.passed(): return 1
    return 0
