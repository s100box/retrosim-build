# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Manifest bench execution and coverage with consumer-owned options."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile

from .manifest import arguments
from .process import run
from .toolchain import ROOT, Toolchain
from .coverage import merge


def fingerprint(argv, config, tool, manifest, root):
    files = {Path(manifest).resolve()}
    def collect(values, active=()):
        for value in values:
            if value.startswith("-I"):
                files.update(p for p in Path(value[2:]).rglob("*") if p.is_file())
            elif not value.startswith("-") and Path(value).is_file():
                source = Path(value)
                files.add(source)
                files.update(source.parent.glob("*.svh"))
                files.update(source.parent.glob("*.vh"))
            elif value.startswith(("-f", "-F")):
                nested = Path(value[2:]).resolve()
                if nested in active: raise ValueError("cyclic nested manifest: " + str(nested))
                files.add(nested)
                collect(arguments(nested, nested.parent if value.startswith("-F") else root), (*active, nested))
    collect(argv)
    files.update(Path(__file__).parent.glob("*.py"))
    tools = Path(__file__).resolve().parents[1]
    files.update([tools / "verilator.cmake", tools / "verilator_msvc.py"])
    files.update(p for p in (tools / "verilator_msvc").iterdir() if p.is_file())
    data = {"argv": argv, "config": config, "tool": tool.provenance(),
            "inputs": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)},
            "driver": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def execute(config_path, *, mode="all", selected="", output=None, jobs=1):
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    here = config_path.parent
    root = (here / config["root"]).resolve()
    output = Path(output or tempfile.mkdtemp(prefix="retrosim-benches-")).resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifests = sorted(p for p in here.glob(config["manifests"]) if selected in p.stem)
    if not manifests:
        raise ValueError(f"no bench matches {selected!r}")
    if mode == "coverage": (output / "merged.dat").unlink(missing_ok=True)
    if jobs < 1 or jobs > config.get("max_jobs", 4):
        raise ValueError("jobs exceeds the suite's resource limit")
    tc = Toolchain()
    env = tc.environment()
    compiler = tc.resolve("VERILATOR" if mode == "coverage" else "IVERILOG")
    timeout = config.get("timeout", 300)

    def bench(manifest):
        name = manifest.stem
        directory = output / name
        directory.mkdir(exist_ok=True)
        args = arguments(manifest, root, verilator=mode == "coverage")
        pattern = config.get("pass_pattern", r"^{name}: PASS").replace("{name}", re.escape(name))
        key = fingerprint(args, config, compiler, manifest, root)
        receipt = directory / "build.json"
        if mode == "coverage":
            obj = directory / "obj"
            # Native program uses an absolute host path, independent of run cwd.
            dat = directory / "coverage.dat"
            dat.unlink(missing_ok=True)
            coverage_args = [str((here / p).resolve()) for p in config.get("coverage_inputs", [])]
            command = [compiler.path, "--binary", "--timing", "-O1", "--coverage-line", "--coverage-toggle",
                       *config.get("coverage_flags", []), *coverage_args,
                       "--top-module", name, "--Mdir", str(obj), "-o", name, *args]
            if os.name == "nt":
                command[0] = "verilator"
                command = [sys.executable, str(ROOT / "tools/verilator_msvc.py"),
                           "--vs-install", tc.resolve("VS_ROOT").path,
                           "--oss-cad-suite", tc.resolve("OSS_CAD_SUITE").path,
                           "--command", shlex.join([value.replace("\\", "/") for value in command])]
        else:
            command = [compiler.path, config.get("standard", "-g2012"),
                       *config.get("compile_flags", []), "-s", name, "-o", str(directory / "bench.vvp"), *args]
        if mode != "run":
            receipt.unlink(missing_ok=True)
            result = run(command, cwd=root, log=directory / "compile.log", timeout=timeout, env=env)
            if not result.passed():
                return name, False, result.log
            receipt.write_text(json.dumps({"fingerprint": key}))
        elif not receipt.exists() or json.loads(receipt.read_text(encoding="utf-8")).get("fingerprint") != key:
            raise ValueError(f"{name}: absent or stale compiled bench; compile first")
        if mode == "compile":
            return name, True, directory / "compile.log"
        if mode == "coverage":
            exe = obj / (name + (".exe" if os.name == "nt" else ""))
            command = [str(exe), "+verilator+coverage+file+" + str(dat)]
        else:
            command = [tc.resolve("VVP").path, *config.get("run_flags", []), str(directory / "bench.vvp")]
        cwd = directory if config.get("run_cwd", "scratch") == "scratch" else root
        result = run(command, cwd=cwd, log=directory / "run.log", timeout=timeout, env=env)
        return name, result.passed(pattern) and (mode != "coverage" or dat.is_file()), result.log

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        results = list(pool.map(bench, manifests))
    for name, passed, log in results:
        print(f"{name}: {'PASS' if passed else 'FAIL'} ({log})")
        if not passed:
            print(log.read_text(encoding="utf-8", errors="replace")[-8000:])
    failed = any(not passed for _, passed, _ in results)
    if mode == "coverage":
        # Only this invocation's successful benches enter the merge. Never glob
        # an old output directory or accept data from failed/omitted benches.
        dats = [str(output / name / "coverage.dat") for name, passed, _ in results if passed]
        if failed or not dats:
            return 1
        summary = config.get("coverage_summary")
        failed |= bool(merge(dats, output, cwd=root, summary=here / summary if summary else None, timeout=timeout, tc=tc))
    print(f"bench suite: {'FAIL' if failed else 'PASS'} -- {len(results)} bench(es); logs in {output}")
    return int(failed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    parser.add_argument("filter", nargs="?", default="")
    parser.add_argument("--mode", choices=("all", "compile", "run", "coverage"), default="all")
    parser.add_argument("--output")
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args()
    try:
        return execute(args.config, mode=args.mode, selected=args.filter, output=args.output, jobs=args.jobs)
    except (ValueError, OSError) as error:
        print(f"bench suite: FAIL: {error}", file=sys.stderr)
        return 1
