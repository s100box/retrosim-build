# Shared host services

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

[README](../README.md) · [Design](retrosim-build-design.md)

## 1. Scope

The Python entry points require Python 3.10 or newer and the standard library.
Consumers execute them from the sibling checkout. They retain source manifests,
board configuration, acceptance patterns and qualification policy. These services
do not establish hardware acceptance or timing closure by themselves.

### Formal suites

`python ../retrosim-build/tools/formal_suite.py sim/formal/suite.json`
runs the consumer's SymbiYosys manifest with the shared tool environment. Add
`--negative` to include intentionally false properties; an optional positional
substring selects job names. `--jobs` defaults to two and cannot exceed the
manifest's `max_jobs`. The consumer still owns the proof scope, clocks, reset
assumptions, engine, depth and properties in its `.sby` files. A bounded `bmc`
PASS establishes only the configured depth; `prove` establishes induction or
reachability. Read the consumer's verification matrix before interpreting results.

The JSON object contains `max_jobs` and a `jobs` array. Each entry names `name`,
`file` (relative to the manifest), optional `task`, `expect` (`PASS` or `FAIL`),
`assert_min`, `cover_min`, and a process `timeout` in seconds. Cover jobs set
`assert_min` to zero and require at least one cover cell. The `.sby` timeout
should be shorter than the process timeout so the tool can clean up its engines.

Each invocation gets fresh job directories under `sim/formal/build/` (override
with `--output`). `audit.json` records status, exit code, retained assertion /
assumption / cover counts, copied source SHA-256 values and work/log paths.
Positive jobs require exit zero and PASS. Negative controls require exit two,
FAIL and a counterexample VCD. Empty models, errors and timeouts fail the suite;
old traces cannot satisfy a new invocation. Keep this output ignored by Git.

## 2. Tool selection and integration checks

`tools/toolchain.py NAME --json` prints a selected path and its provenance.
Python callers add this repository's `tools` directory to `sys.path`, then use
`retrosim_build.toolchain.Toolchain().resolve(NAME)` or `.environment()`.
The resolver expands Ninja variables, rejects cycles and undefined variables,
and chooses live environment overrides before shared pins and discovery.
`VSINSTALL` remains the legacy Visual Studio override. Root selections must be
directories; executable selections must be files. Windows Verilator tools use
native executables when the distribution supplies Perl wrappers.

```sh
python ../retrosim-build/tools/audit_consumers.py .
```

The integration checker scans tracked build metadata for private tool roots,
literal Windows Bash pins, missing primary-hook bootstrap and missing shared
helper paths. It excludes vendored implementation directories. A justified
exception belongs in `.retrosim-tooling.json` as an `exceptions` entry with
`path`, `rule` and `reason`; use the rule name printed by the checker.
Primary commit/push hooks sourcing `hooks/gate-env.sh` run the checker automatically.

## 3. Manifest benches and coverage

```sh
python ../retrosim-build/tools/bench_suite.py pl/sim/suite.json uart --jobs 2
python ../retrosim-build/tools/bench_suite.py pl/sim/suite.json --mode coverage --output tmp/coverage
```

The optional positional filter selects manifest stems by substring. Modes are
`all`, `compile`, `run` and `coverage`. Jobs default to one and cannot exceed
the consumer's `max_jobs`. Every child has a timeout, a fresh log and an explicit
exit status. Nonzero exits are written into the log, with the Windows status
also shown in hexadecimal so an early native crash remains diagnosable.
A run passes only with exit zero and the configured marker.
Run-only mode requires a matching content-bound compile receipt.

The JSON suite fields are:

| Field | Contract |
|---|---|
| `root`, `manifests` | Source root and manifest glob relative to the configuration directory. |
| `standard`, `compile_flags`, `run_flags` | Icarus language selection, compiler options and vvp options. |
| `timeout`, `max_jobs` | Per-child seconds and suite concurrency limit; defaults 300 and 4. |
| `pass_pattern` | Multiline regular expression; `{name}` expands to the escaped manifest stem. |
| `run_cwd` | `scratch` (default) or a different value to use the source root. |
| `coverage_inputs`, `coverage_flags` | Verilator-only inputs relative to the configuration directory, and options. |
| `coverage_summary` | Optional Python summary script relative to the configuration directory; receives merged data. |

Manifests contain one source path or option per line, with `#` comments and
shell-style quoting. Use forward slashes in portable paths. Include and nested
manifest options accept `-I`, `-f` and `-F`. Verilator omits Icarus `-g` options.
Per-bench working directories keep runtime files separate. Explicit output
directories retain build objects for inspection and incremental vendor builds;
default runs use a fresh temporary directory.

Coverage uses native MSVC on Windows and Verilator's binary driver on POSIX.
Only data produced by successful benches selected in this invocation is merged;
failed runs block reporting. The public `tools/coverage_merge.py --output DIR
INPUT...` entry point merges explicit nonempty inputs and optionally annotates
or runs `--summary SCRIPT`. Python callers may supply named merge groups, whose
members must be within the same input set. `tools/run_logged.py` gives bespoke
drivers the same timeout, exit and marker checks; see its `--help` for options.

CMake consumers include `tools/verilator.cmake` after `find_package(verilator)`
and call `retrosim_verilate` with an explicit `PREFIX` and the usual `verilate`
arguments. Generated output must stay inside the target's build tree. The
wrapper watches discovered HDL and includes, refreshes the JSON-derived C++
split list during configure, and bypasses Verilator's separate timestamp cache.
Unchanged generated C++ retains its timestamps and compiled objects. Quoted JSON
list entries preserve source/build paths containing spaces. The native driver
and the release repositories' CMake coverage projects use this interface.

## 4. Native Windows build snapshots

`tools/vl_build.ps1` retains its CMake interface and adds `-Top`, `-ArgsFile`,
`-Coverage`, `-DestinationDir` and `-Jobs` for snapshot consumers. Argument files
contain one source or Verilator option per line, relative to `-SourceDir`.
The consumer CMake project accepts `TOP`, `SRCS`, `VDEFS` and `VL_COVERAGE`,
and emits `${TOP}_vl.exe`. The shared driver publishes `${TOP}_vl.exe` or
`${TOP}_cov.exe` to the destination directory (default `../obj_dir`).

Normal and coverage configurations have distinct per-top build directories.
Keys bind source/header contents, arguments, CMake inputs, relevant build
environment, tool binaries, shared pins and helper code. Configuration is skipped
only with a matching key; incremental compilation still runs. A receipt is
published after successful build and executable copy. Copy failure is fatal.
Changed keys use CMake's `--fresh` mode (CMake 3.24 or newer) so a removed
compiler installation cannot survive in CMake's internal cache.
Vendor CMake parsers require Windows short-path aliases when paths contain spaces;
the driver reports a missing alias instead of silently splitting such paths.

## 5. External programming artifacts

`tools/program_fpga.py` accepts explicit `--artifact`, `--report`, `--sdc`,
one or more `--source` paths, `--board` and `--mode sram|flash`. It requires
both artifact and report to be at least as new as the declared source inputs,
then invokes the shared timing sign-off gate. `--check-only` stops after those
checks. Consumers must include every generated memory and build-policy input
that can affect their image. There is no stale-artifact bypass in this API.

Programming uses the canonical board operations in `gowin.sh`; SRAM is the
default and persistent flash requires explicit selection. `--device` can assert
the expected board device. Repeat `--programmer-arg=VALUE` for cable arguments;
values remain individual arguments even when they contain spaces. The CLI
preflight must succeed before the internal `tools/gowin_program.sh` dispatcher
is invoked. Existing in-tree `gowin_prog` callers retain their freshness gates.

## 6. Tree and citation policy

`tools/check_tree.py --root ROOT --policy POLICY` checks configurable LF,
whitespace, SPDX and Markdown links, including anchors. Consumers retain
extension lists, ownership exemptions and binary/generated/evidence exclusions
in JSON. Sealed evidence exclusions preserve the original files and hashes.
Sibling links can resolve through the workspace; unavailable siblings are not
checked as if their contents were present.

`tools/check_citations.py POLICY --root ROOT` validates numbered
document authorities. Policies retain plan/board identifiers, family-specific
attribution expressions, self-check probes and optional qualified two-authority
rules. The shared engine does not supply CPU semantics. Thin local shims keep
existing command names; the rig policies are working examples of both formats.
Qualified policies may supply `candidate_literals` for Git's tracked-text
prefilter; those literals must cover every supported citation pattern. Policies
are always read as UTF-8, independently of the host's default text encoding.

## 7. Vivado Tcl primitives

Source `vivado.tcl` once from the sibling checkout. The `retrosim` namespace
provides `require_files`, `create_project NAME DIRECTORY PART ?EXTRA?`,
`check_ports PORTS`, `reject_latches`, and
`cached_ip IP_DIR OUTPUT_ROOT DEPENDENCIES EXPECTED PRODUCER ?SETTINGS?`.
Port checks require PACKAGE_PIN and IOSTANDARD; latch checks reject inferred
latches. Consumers choose when these checks apply.

The IP cache binds declared dependency contents, producer Tcl, settings,
Vivado version and helper identity. Consumers must declare all IP configuration
inputs and part settings. Invalidation removes only the declared IP directory,
which must be strictly within the owned output root; the expected output must
be inside it. The producer runs in its caller's scope. A failed producer or
missing expected output never publishes a valid receipt. Python must be on
PATH or selected with `PYTHON3`. Board pin maps, IP configuration, synthesis,
timing decisions and hardware procedures remain in consumer Tcl.

## 8. Verification

The host test suite exercises failure propagation, stale receipts, tool
selection, source/tool/environment cache invalidation, programming preflight,
mock programmer operations, policy checks and Tcl cache ownership. Tcl unit
tests use Python's headless Tcl interpreter and require `tkinter`; they do not
launch Vivado. Live consumer checks complement these fixtures. See the
[integration review](rtl-tooling-review.md#validation-boundaries) for boundaries.
