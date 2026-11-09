#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Content-bound CMake configure key for per-top Verilator builds."""
import argparse
import hashlib
import json
import os
from pathlib import Path


def key(source, args_file, settings, tools, include_roots=(), environ=None):
    source = Path(source).resolve()
    items = Path(args_file).read_text(encoding="utf-8-sig").splitlines()
    inputs = {Path(args_file).resolve(), Path(__file__).resolve()}
    inputs.update(source.glob("CMakeLists.txt"))
    inputs.update(source.glob("*.cmake"))
    for value in items:
        if not value:
            continue
        if value.startswith("-I"):
            directory = Path(value[2:])
            if not directory.is_absolute(): directory = source / directory
            inputs.update(p for p in directory.rglob("*") if p.is_file())
        elif not value.startswith("-"):
            path = Path(value)
            path = path if path.is_absolute() else source / path
            inputs.add(path)
            inputs.update(path.parent.glob("*.svh"))
            inputs.update(path.parent.glob("*.vh"))
    for root in include_roots:
        inputs.update(p for p in Path(root).rglob("*") if p.is_file() and p.suffix in (".h", ".cpp", ".cmake"))
    inputs.update(Path(path).resolve() for path in tools)
    environment = os.environ if environ is None else environ
    selected = {name: environment.get(name) for name in (
        'CC','CXX','CFLAGS','CXXFLAGS','CPPFLAGS','LDFLAGS','CMAKE_TOOLCHAIN_FILE',
        'INCLUDE','LIB','LIBPATH','VCToolsVersion','WindowsSdkDir','WindowsSDKVersion','CL','_CL_')}
    data = {"settings": settings, "arguments": items, "environment": selected, "files": {
        str(path.resolve()): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(inputs)}}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("args_file")
    parser.add_argument("--setting", action="append", default=[])
    parser.add_argument("--tool", action="append", default=[])
    parser.add_argument("--include-root", action="append", default=[])
    args = parser.parse_args()
    print(key(args.source, args.args_file, args.setting, args.tool, args.include_root))
