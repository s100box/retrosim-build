#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Build one self-contained SystemVerilog bench with Verilator and MSVC.

This is the shared Windows equivalent of ``verilator --binary --timing``.
It imports the Visual Studio 2026 amd64 environment and drives Verilator's
official CMake integration with VS's bundled Ninja.
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
PROJECT = HERE / "verilator_msvc"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from retrosim_build.toolchain import Toolchain
_default_vs = Toolchain().resolve("VS_ROOT", required=False)
DEFAULT_VS = Path(_default_vs.path) if _default_vs else None


def die(message: str) -> None:
    raise SystemExit(f"verilator_msvc: {message}")


def vcvars_environment(vcvars: Path, base: dict[str, str]) -> dict[str, str]:
    command = f'call "{vcvars}" amd64 && set'
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=base,
        shell=True,
    )
    if result.returncode:
        die(
            f"vcvarsall failed with exit {result.returncode}: "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
    environment = base.copy()
    for line in result.stdout.splitlines():
        if "=" in line:
            name, value = line.split("=", 1)
            environment[name] = value
    return environment


def parse_binary_command(command: str, cwd: Path) -> tuple[str, Path, Path, list[Path], list[str]]:
    """Translate the common ``verilator --binary`` CLI into this helper's inputs."""
    words = shlex.split(command, posix=True)
    if not words or Path(words[0]).name not in ("verilator", "verilator.exe"):
        die("--command must begin with verilator")
    top: str | None = None
    mdir = Path("obj_dir")
    output_name: str | None = None
    sources: list[Path] = []
    verilator_args: list[str] = []
    index = 1
    while index < len(words):
        word = words[index]
        if word in ("--binary", "--timing"):
            index += 1
            continue
        if word in ("--Mdir", "-Mdir", "--top-module", "-o", "-j"):
            if index + 1 >= len(words):
                die(f"missing value after {word} in --command")
            value = words[index + 1]
            if word in ("--Mdir", "-Mdir"):
                mdir = Path(value)
            elif word == "--top-module":
                top = value
            elif word == "-o":
                output_name = value
            index += 2
            continue
        if word.startswith((">", "1>", "2>")) or word in ("2>&1", "1>&2"):
            index += 1
            continue
        if word.startswith("-I") and len(word) > 2:
            include = (cwd / word[2:]).resolve()
            verilator_args.append("-I" + str(include))
        elif Path(word).suffix.lower() in (".sv", ".v", ".vlt"):
            sources.append((cwd / word).resolve())
        else:
            verilator_args.append(word)
        index += 1
    if not top:
        die("--command is missing --top-module")
    if not sources:
        die("--command contains no Verilog sources")
    # Match ``verilator --binary``: without an explicit ``-o``, the generated
    # executable is named after the C++ model class, including its leading V.
    output_name = output_name or f"V{top}"
    if not output_name.lower().endswith(".exe"):
        output_name += ".exe"
    output = (cwd / mdir / output_name).resolve()
    build_dir = (cwd / mdir / f"msvc-{top}").resolve()
    return top, build_dir, output, sources, verilator_args


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top", help="SystemVerilog top module")
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--output", type=Path, help="copy the built executable here")
    parser.add_argument("--source", type=Path, action="append")
    parser.add_argument("--verilator-arg", action="append", default=[])
    parser.add_argument("--main", type=Path, help="a C++ driver in place of sim_main.cpp")
    parser.add_argument(
        "--force-include",
        type=Path,
        help="a header forced into every C++ source (verilator_msvc/vl_save_queue.h for --savable)",
    )
    parser.add_argument(
        "--no-timing",
        action="store_true",
        help="build without --timing (the driver clocks the bench; --savable needs it)",
    )
    parser.add_argument(
        "--command",
        help="compatibility input: one quoted verilator --binary command",
    )
    parser.add_argument(
        "--vs-install",
        type=Path,
        default=DEFAULT_VS,
    )
    parser.add_argument(
        "--oss-cad-suite",
        type=Path,
        default=None,
    )
    args = parser.parse_args()

    if args.command:
        if args.top or args.build_dir or args.output or args.source or args.verilator_arg:
            parser.error("--command cannot be combined with explicit build inputs")
        top, build_dir, output, sources, verilator_args = parse_binary_command(
            args.command, Path.cwd()
        )
    else:
        if not args.top or not args.build_dir or not args.source:
            parser.error("--top, --build-dir, and at least one --source are required")
        top = args.top
        build_dir = args.build_dir.resolve()
        output = args.output.resolve() if args.output else None
        sources = [path.resolve() for path in args.source]
        verilator_args = args.verilator_arg

    toolchain = Toolchain()
    vs = args.vs_install.resolve() if args.vs_install else Path(toolchain.resolve("VS_ROOT").path).resolve()
    oss = args.oss_cad_suite.resolve() if args.oss_cad_suite else Path(toolchain.resolve("OSS_CAD_SUITE").path).resolve()
    cmake = vs / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
    ninja = vs / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe"
    vcvars = vs / "VC/Auxiliary/Build/vcvarsall.bat"
    verilator_root = oss / "share/verilator"
    for description, path in (
        ("Visual Studio CMake", cmake),
        ("Visual Studio Ninja", ninja),
        ("Visual Studio vcvarsall", vcvars),
        ("Verilator CMake package", verilator_root / "verilator-config.cmake"),
    ):
        if not path.exists():
            die(f"{description} not found: {path}")

    missing = [path for path in sources if not path.exists()]
    if missing:
        die("source not found: " + ", ".join(str(path) for path in missing))

    environment = os.environ.copy()
    environment["VERILATOR_ROOT"] = verilator_root.as_posix()
    # verilator_bin.exe is run during configure. Both directories are needed;
    # omitting lib produces Windows exit 0xc0000135 (the misleading DLL popup).
    environment["PATH"] = os.pathsep.join(
        (str(oss / "bin"), str(oss / "lib"), environment.get("PATH", ""))
    )
    environment = vcvars_environment(vcvars, environment)
    # Verilator writes PYTHON3 verbatim into a generated CMake file.  Native
    # Windows backslashes (notably ``\U`` in C:\Users) are CMake escapes, so
    # keep the executable equivalent while making the generated string safe.
    if environment.get("PYTHON3"):
        environment["PYTHON3"] = Path(environment["PYTHON3"]).as_posix()

    configure = [
        str(cmake),
        "-S",
        str(PROJECT),
        "-G",
        "Ninja",
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_MAKE_PROGRAM={ninja}",
        f"-DCMAKE_PREFIX_PATH={verilator_root}",
        f"-DTOP={top}",
        "-DSRCS=" + ";".join(str(path) for path in sources),
        "-DVDEFS=" + ";".join(verilator_args),
        "-DMAIN=" + (args.main.resolve().as_posix() if args.main else ""),
        "-DTIMING=" + ("OFF" if args.no_timing else "ON"),
        "-DFORCE_INCLUDE=" + (args.force_include.resolve().as_posix() if args.force_include else ""),
    ]
    print("+", subprocess.list2cmdline(configure), flush=True)
    subprocess.run(configure, check=True, env=environment)
    build = [str(cmake), "--build", str(build_dir)]
    print("+", subprocess.list2cmdline(build), flush=True)
    subprocess.run(build, check=True, env=environment)

    executable = build_dir / f"{top}_vl.exe"
    if not executable.exists():
        die(f"build succeeded but executable is missing: {executable}")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(executable, output)
        executable = output
    print(f"verilator_msvc: {executable}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode)
