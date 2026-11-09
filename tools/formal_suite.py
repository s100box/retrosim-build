#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Run declared SymbiYosys jobs and reject empty or unsubstantiated verdicts.

Consumers own their properties, assumptions and task configuration. This driver
owns fresh work directories, bounded execution and the retained-cell census.
Negative controls must produce a real FAIL trace; an ERROR is never success.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from retrosim_build.process import run
from retrosim_build.toolchain import Toolchain


def run_job(job, config_dir, output, env):
    """Run one manifest job and audit its prepared model and status file."""
    name = job["name"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        raise ValueError("unsafe formal job name: " + name)
    config = (config_dir / job["file"]).resolve()
    # Unique owned directory: an early tool failure cannot reuse an old FAIL
    # trace or a previous successful status as evidence for this invocation.
    work = Path(tempfile.mkdtemp(prefix=name + "-", dir=output))
    log = output / (name + ".log")
    sby = shutil.which("sby", path=env["PATH"])
    if not sby:
        raise FileNotFoundError("sby: install/configure the OSS CAD Suite")
    command = [sby, "-f", "-d", str(work), str(config)]
    if job.get("task"):
        command.append(job["task"])
    process = run(command, cwd=config.parent, env=env, log=log,
                  timeout=job.get("timeout", 300))
    code = "timeout" if process.timed_out else process.returncode
    status_file = work / "status"
    status = status_file.read_text().split()[0] if status_file.exists() else "MISSING"
    model = work / "model/design_prep.il"
    text = model.read_text(encoding="utf-8") if model.exists() else ""
    cells = {kind: len(re.findall(r"^\s*cell \$" + kind + r"\s", text, re.M))
             for kind in ("assert", "assume", "cover")}
    expected = job.get("expect", "PASS")
    verdict = (status == expected and
               ((code == 0 and expected == "PASS") or
                (code == 2 and expected == "FAIL" and any(work.glob("engine_*/trace*.vcd")))))
    verdict &= cells["assert"] >= job.get("assert_min", 1)
    verdict &= cells["cover"] >= job.get("cover_min", 0)
    sources = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
               for p in sorted((work / "src").glob("*")) if p.is_file()}
    result = {"pass": bool(verdict), "expected": expected, "status": status,
              "exit": code, "cells": cells, "sources": sources,
              "log": str(log), "work": str(work)}
    print(f"{name}: {'PASS' if verdict else 'FAIL'}; {status}, cells={cells}", flush=True)
    return name, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("filter", nargs="?", default="")
    parser.add_argument("--negative", action="store_true", help="include declared negative controls")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = args.manifest.resolve()
    manifest = json.loads(config.read_text())
    if not 1 <= args.jobs <= manifest.get("max_jobs", 2):
        parser.error("jobs exceeds the declared concurrency limit")
    jobs = [j for j in manifest["jobs"] if args.filter in j["name"] and
            (args.negative or j.get("expect", "PASS") != "FAIL")]
    if not jobs or len({j["name"] for j in jobs}) != len(jobs):
        parser.error("no jobs selected, or duplicate job names")
    output = (args.output or config.parent / "build").resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = Toolchain().environment()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = dict(pool.map(lambda j: run_job(j, config.parent, output, env), jobs))
    (output / "audit.json").write_text(json.dumps(results, indent=2) + "\n")
    return int(not all(r["pass"] for r in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
