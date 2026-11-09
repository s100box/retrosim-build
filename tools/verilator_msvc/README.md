# Verilator/MSVC helper

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

Native Windows build support for self-contained SystemVerilog testbenches.

## Documentation

See [host setup](../../doc/host-build-tools.md) for tool installation and the
[build design](../../doc/retrosim-build-design.md) for shared helper responsibilities.

## Repository layout

`../verilator_msvc.py` is the Python driver; this directory holds its CMake
project template. Callers supply source files and an isolated build directory.

## Requirements

Visual Studio 2026 with the amd64 compiler and bundled CMake/Ninja, Python 3.10+,
and Verilator from the OSS CAD Suite. `VSINSTALL` and `OSS_CAD_SUITE` override
the default locations. The driver adds both the suite's `bin` and `lib`
directories to PATH to satisfy Verilator's runtime dependencies.

## Getting started

Call the driver with one `--source` per RTL or bench file, `--build-dir`,
and optionally `--output`. Run `python ../verilator_msvc.py --help` from
this directory for all options. Native `PYTHON3` paths are normalized before
Verilator writes them into generated CMake files.

Existing Git Bash gates can pass a complete Verilator command:

```sh
python ../verilator_msvc.py --command \
  "verilator --binary --timing --Mdir obj_dir --top-module tb_top rtl.sv tb_top.sv -o tb_top"
```

Source and include paths resolve against the caller's working directory.
This form builds under `obj_dir/msvc-tb_top` and copies the executable to
`obj_dir/tb_top.exe`. Without `-o`, it uses `obj_dir/Vtb_top.exe`.
Both `-Mdir` and `--Mdir` are accepted by the compatibility parser.

MSVC executables reserve 64 MiB of main-thread stack address space for timing
and coverage benches with large temporary arrays. This replaces MSVC's 1 MiB
default; it does not commit the entire reserve as physical memory.

The CMake template uses [`retrosim_verilate`](../verilator.cmake) to refresh
split C++ source lists and track included HDL changes. Other CMake consumers
include that helper after `find_package(verilator)` and retain their normal
arguments, with an explicit `PREFIX`. Generated output stays inside the build
tree; the helper removes only its generator receipt.

## Verification

The driver reports configure and compiler failures. Run the resulting bench
and check its exit status and self-checking verdict in the consuming project;
a successful build alone does not establish RTL correctness.

The default host suite tests the cache and path policy without a C++ compiler.
On Windows with the tools above installed, run the opt-in native regression:

```sh
python tests/native_verilator_incremental.py
```

Run it from the repository root. It exercises both the driver and a consumer
CMake project in paths with spaces, changes an included HDL file to expand the
split source set, checks the rebuilt executable, and rejects invalid HDL.

## License

See the repository [license](../../README.md#license).
