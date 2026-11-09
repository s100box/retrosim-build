# retrosim-build design

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

For setup, build commands, and commit checks, see the [README](../README.md).
This document defines the design and its verification scope.

**Contents**

- [1. Purpose](#1-purpose)
- [2. Components](#2-components)
- [3. Consumer conventions](#3-consumer-conventions)
- [4. Timing sign-off](#4-timing-sign-off)
- [5. Programming and UART capture](#5-programming-and-uart-capture)
- [6. Verification](#6-verification)

## 1. Purpose

Shared shell, PowerShell, Python, and Ninja infrastructure supplies tool
discovery, FPGA builds, programming checks, and simulation support to sibling
repositories. Consumers source or execute files in place and retain their
own source manifests, board constraints, and test verdicts.

## 2. Components

| Path | Purpose |
|---|---|
| `toolchain.ninja` | Workspace tool configuration — the single file a tool version bump edits. Ninja-syntax `name = value` (gowin_root / verible_root / oss_cad_suite / vs_root / sdcc_root + derived gwsh / programmer_cli / gowin_simlib / verible_*). Consumed by Ninja, shell, PowerShell and Python: ninja files `include` it directly; `gowin.sh` and `hooks/gate-env.sh` parse it (explicit env always wins, and a set-but-dead env path falls through to the pin with a warning); PowerShell scripts dot-source `toolchain.ps1`; Python callers use `retrosim_build.toolchain`. Never add a version-pinned tool path to any other repo. |
| `toolchain.ps1` | PowerShell side of the pin: dot-source it and use `$env:GWSH` / `$env:PROGRAMMER_CLI` / `$env:VS_ROOT` / `$env:VERIBLE_ROOT` / `$env:OSS_CAD_SUITE` / `$env:SDCC_ROOT` (set only where not already in the environment). |
| `fpga_common.sh` | Vendor-neutral pieces shared by `gowin.sh` and `vivado.sh` — the bitstream freshness gate (`retrosim_fs_freshness`). Exclusion settings: `$RETROSIM_FS_IGNORE` drops paths outright (the other VENDOR's flow); `$RETROSIM_FS_TARGET_PATTERNS` holds `%s`-shaped globs so the other ARM's generated inputs are exempt while this arm's own copy stays gated; and **`$RETROSIM_FS_TARGET_GLOB`** (default `*`) is what `%s` expands to for *the other target*. ⛔ The default is wide enough to swallow a hand-written source when generated and hand-written files share a directory — hh-j11's `syn/a7lite/` is exactly that case — so a repo in that shape must narrow it (there: `j11_a7lite_*`) or the gate silently stops protecting the pin/constraint edits it exists for. Sourced by both libraries, never directly by a repo. |
| `vivado.sh` | The Xilinx counterpart of `gowin.sh`: `vivado_board`, `vivado_run` (filtered console + full transcript tee), `vivado_synth`, `vivado_prog`/`vivado_prog_flash` (freshness-gated on the build's own artifacts; data-region MCS writes stay ungated), `vivado_available`/`vivado_require` (127 = toolchain absent, not a build failure). Resolves via `$VIVADO` → the pin's `vivado_root` → PATH → newest-install discovery, with the same dead-env fallthrough as gowin.sh. |
| `tools/timing_signoff.py` | The one Gowin timing sign-off gate (per-clock TNS Setup+Hold, Fmax margins, dead-path-exception check, SDC-Constraints "Actived" health gate, optional `--ship` over-constraint waiver). |
| `gowin.sh` | Sourced shell library: `gowin_board` (the canonical board table, legacy aliases accepted), `gowin_synth` (host-global build lock + gw_sh retry + impl rename + sign-off), `gowin_prog`/`gowin_prog_flash` (guarded by the **bitstream freshness gate** — refuse when RTL/SDC under `$GOWIN_RTL_DIRS` is newer than the `.fs`; `ALLOW_STALE_BITSTREAM=1` overrides), `gowin_prog_data` (external-flash data region at `--spiaddr`, with the GAO-bridge fast-fail retry), `gowin_require` (fail loudly before a 40-minute slot is spent), `gowin_report_synth_health` (the one-line warns/swept/latch/fmax record and optional fatal gates). Gowin consumers source it from their build scripts. |
| `tools/gen_gprj_lib.py` | Shared `.core`→`.gprj` engine (fileset load, file-list assembly, XML emit + validation, `--check` drift gate, `--stage-config`) **plus `GOWIN_BOARDS`** — the one device/part/devid table (the Python mirror of gowin.sh's board table; keep them in lockstep). Each repo's `tools/gen_gprj.py` is a thin shim declaring only its filesets + assembly. Fifteen repos generate their `.gprj` this way. |
| `tools/vs_env.ps1` | Dot-source to import the VS amd64 build environment (resolved through the toolchain pin); exports `$RetrosimCMake`/`$RetrosimNinja` and defaults `VERILATOR_ROOT` from the pinned oss-cad-suite. |
| `tools/vl_build.ps1` | Native Verilator/MSVC CMake driver. The existing CMake interface and the `-Top`/`-ArgsFile` snapshot interface share tool discovery. Snapshot builds use per-top normal/coverage directories and content-bound reconfiguration keys, and publish receipts after successful executable copy. |
| `tools/retrosim_build/` | Python APIs for tool selection, bounded processes, manifest benches, explicit coverage merges, programming preflight and configurable tree/citation validation. CLI entry points live directly in `tools/`. |
| `tools/audit_consumers.py` | Build-metadata integration checks, also invoked by primary hooks through `gate-env.sh`. Consumer exceptions require a path, rule and reason. |
| `vivado.tcl` | Small source-only project, IP-cache, port and latch primitives. Consumers retain board/IP configuration and vendor-flow sequencing. |
| `tools/vl_cov_lib.ps1` + `tools/vl_cov.ps1` | The Verilator code-coverage suite. `vl_cov_lib.ps1` (dot-source) holds the steps every repo's `sim/vl/cov.ps1` shares: `Initialize-VlCov` (paths + the toolchain pin), `Build-VlCov` (VL_COVERAGE=ON twins; optional `-FailOnUnoptflat`, since an UNOPTFLAT under `-Wno-fatal` over-counts comb coverage, and `-Require`d exes), `Invoke-VlCovRun` (one run into `dat/cov_<name>.dat`, a PASS / FAIL / done verdict from the exit code and output patterns, an optional merge group) and `Complete-VlCov` (merge into `report/merged_all.dat` plus one `merged_<group>.dat` per group, lcov `.info`, `--annotate` tree; nonzero when any run failed). `vl_cov.ps1` is the whole driver for a suite that is "run every `vl-*.exe` twin", so such a repo's `cov.ps1` is three lines; repos with ROM images, oracle diffs or per-bench build trees keep their run list and call the library. |
| `tools/cov_summary_lib.py` | Renders a repo's committed coverage baseline (`doc/coverage.md`) from those merged `.dat`s: the parser, per-file line / branch / toggle cells, column groups (fixed or discovered from `merged_*.dat`), scoped sections, notes, an optional totals row and per-file line-gate table, `--holes`, and the hand-written `## Hole triage` section kept across regenerations. A point is merged by logical identity, dropping both `h` (hierarchy instance) and `page` (module specialization, the `__Sz1` suffix), so a module instantiated or re-parameterized several times is counted once. Each repo's `tools/cov_summary.py` declares only a `Report` (title, prose, scope, notes). Thirteen repos use the pair. |
| `tools/build-dasm-tools.sh` | Builds the host binary-analysis pair from anywhere in the workspace: `dasmxx` (the disassembler suite) and `macro11` (the MACRO-11 assembler under `pdp11-docs`). Picks the CMake and generator that actually work per host, and `--test` runs both gates (dasmxx ctest; the macro11 CZTUKA0 assemble-and-compare round trip). |
| `tools/build-vax-binutils.sh` | Builds native Windows GNU VAX assembler/linker/disassembler tools with MSYS2 MinGW64. Runtime use needs no WSL or MSYS DLL; the native winpthreads DLL is bundled. [Provenance, build and validation](vax-binutils-windows.md). `toolchain.ps1` exports the shared `vax_binutils_root` pin as `VAX_BINUTILS_ROOT`. |
| `tools/xcheck-links.py` | Relative Markdown link checker. Accepts a workspace `--root`, selected files/directories, optional `--anchors` validation for deep links, and `--present MANIFEST` for files kept outside git (a link to a manifested path resolves whether or not it is fetched). This is the single implementation used by `pdp11-docs`; its hook finds the sibling checkout or the path named by `RETROSIM_BUILD`. |
| `tools/uart_prog_capture.py` | Generic Python 3 silicon runner: opens a serial console before invoking any caller-supplied programmer command, rejects stale pre-load bytes using a marker, preserves programmer failures, logs the accepted UART stream, and gates caller-supplied verdict strings. Opens the port through a serbridge when one holds it (`tools/bridgeport.py`). Requires `pyserial`. |
| `tools/verilator_msvc.py` + `tools/verilator_msvc/` | Generic Windows Verilator bench builder using Visual Studio 2026, its bundled CMake/Ninja, and the complete OSS CAD Suite DLL path. This is the reusable fix for the missing-DLL popup caused by launching `verilator_bin.exe` with only `bin` on `PATH`. |
| `tools/ihx2mem.py` | Shared Intel HEX window converter for SDCC firmware: emits byte-per-line `$readmemh` data and, optionally, the byte-identical raw binary used in a separate SPI-flash payload. |
| `hooks/gate-env.sh` | Shared hook environment, sourced first by every `.githooks` hook: the `SKIP_GATE=1` bypass and robust Verible/oss-cad discovery that **re-prepends** the tool dirs (fixing the Git-for-Windows DLL-shadowing failure where iverilog dies silently only under `git commit`). |
| `templates/` | `.gitattributes` (RTL-only + Rust-mixed flavors) and the base `.rules.verible_lint` for new repos. |
| `WORKFLOW-TEMPLATE.md` | The shared WORKFLOW.md section taxonomy every repo follows. |

The methodology behind the sign-off rules is
`../../ts804fpga/doc/gowin-timing-closure.md` — read it before changing the gate.

The [host service reference](host-services.md) defines the Python, snapshot,
external-artifact programming and Tcl interfaces, including their configuration
fields and cache ownership contracts.

## 3. Consumer conventions

### Build.sh convention

This is the convention for multi-board consumers. Dedicated board projects
can use a target-first interface; for example, `hh-xcku5p-dev` uses
`build.sh <target> <rate> [coupling]`, and `mega138kpro-sfp` uses
`build.sh <target> <rate>`. Follow each consumer's README.

```
./build.sh <board> [<variant>] [<target>]     # target defaults to synth
./build.sh all                                # every valid board×variant combo
./build.sh gprj [--check] | config            # project-file maintenance verbs

targets: lint | sim | synth | rom | gprj | config | prog | prog-flash
```

- **Board first, variant second, target last.** The variant slot is
  repo-defined (CPU core, ROM personality, engine config, SoC flavor) and
  omitted in repos that have none.
- `prog` = volatile SRAM load; `prog-flash` = persistent (SPI/embedded
  flash). A repo without hardware verbs errors with a clear message rather
  than silently succeeding.
- Environment: `GWSH` (gw_sh path), `PROGRAMMER_CLI` (programmer_cli path),
  `PROGDEV` (extra cable args when a host differs from the table below).
  Drivers set `QT_PLUGIN_PATH=""` themselves.
- A successful Gowin build requires successful vendor-tool execution and
  timing sign-off: TNS (Setup and Hold) after SDC exceptions, dead-exception
  checks, Actived health, and the `--ship` waiver where a consumer deliberately
  over-constrains. Consumer-specific validation can impose additional gates.

### Canonical board names

Use the canonical board names below when selecting a target:

| Canonical name | Board | Device | Part | Programmer args | SRAM load | Flash persist |
|---|---|---|---|---|---|---|
| `nano20k` | Sipeed Tang Nano 20K | `GW2AR-18C` | `GW2AR-LV18QN88C8/I7` | *(default cable)* | `--run 24` + `--run 2` | `--run 8` (external SPI), verified with `--run 11`; data regions via `--run 36 --spiaddr` |
| `primer20k` | Sipeed Tang Primer 20K | `GW2A-18C` | `GW2A-LV18PG256C8/I7` | `--device GW2A-18C --location 593` ⚠️ | `--run 24` + `--run 2` | `--run 8`, then reconfigure and check DONE |
| `primer25k` | Sipeed Tang Primer 25K | `GW5A-25A` | `GW5A-LV25MG121NES` | *(default cable)* | `--run 24` + `--run 2` | `--run 54` |
| `console60k` | Sipeed Tang Console / Mega 60K | `GW5AT-60B` | `GW5AT-LV60PG484AC1/I0` | `--device GW5AT-60B --location 289` ⚠️ | `--run 24` + `--run 2` | `--run 54` |
| `console138k` | Sipeed Tang Console 138K (60K-footprint SOM) | `GW5AST-138C` | `GW5AST-LV138PG484AC1/I0` | `--device GW5AST-138C --location 6689` ⚠️ | `--run 24` + `--run 2` | `--run 54` |
| `mega138kpro` | Sipeed Tang Mega 138K Pro (676-ball core board) | `GW5AST-138B` | `GW5AST-LV138FPG676AC1/I0` | `--device GW5AST-138B` + host `PROGDEV` | `--run 24` + `--run 2` | `--run 54` |

> ⚠️ **USB `--location` is host/session-dependent.** Verify the cable with
> `programmer_cli --scan --location <N>` before programming and set `PROGDEV`
> for your host. The numeric locations in the table are defaults, not board identities.
>
> ⚠️ **A fresh Windows host needs the FTDI VCP driver first** (<https://ftdichip.com/drivers/vcp-drivers/> — the setup executable installs VCP + D2XX). Without it the Sipeed on-board debugger (FT2232, `VID_0403&PID_6010`) enumerates as an unknown "USB Composite Device", `programmer_cli --scan-cables` exits 48 with no cables, and the debugger's UART channel gets no COM port. Install, then replug the board (see `doc/host-build-tools.md` gotcha 8).

This table lives in `gowin.sh` (`gowin_board`), which also accepts the
compatibility aliases such as tang_mega60k, tang138k and tang_nano_20k. `PROGDEV` (when set)
**replaces** the table's cable/location args for hosts whose cabling
differs (find yours with `programmer_cli --scan-cables`); the `--device`
always comes from the table.

### Sim-side target names (ninja)

`ninja` (default) = at least the Verible syntax+lint+format-check trio;
the simulation target is consumer-specific (`ninja unit`, `ninja bench` or
`ninja sim`). Follow its README. Differential co-simulations, ROM tests and
drift checks are additional gates where provided.

## 4. Timing sign-off

```sh
python ../../retrosim-build/tools/timing_signoff.py \
    impl_<base>/pnr/<base>_tr_content.html  boards/<board>/<board>.sdc \
    [--ship 66.667] [--ship-clock clk_core]
```

Exit 0 = met, 1 = violations / Fmax below ship / dead constraints,
2 = report parse failure. `--ship` waives ONLY the ship clock's Setup TNS,
and only while the delivered Fmax still clears the silicon clock — Hold rows
and every other clock always gate.

## 5. Programming and UART capture

`tools/uart_prog_capture.py` implements the shared silicon-runner seam: it opens
the UART first, runs a repo-owned programming command, discards output from the
previous image until a marker, and gates exact verdict strings. Repositories keep
their own protocol-specific markers and acceptance criteria. Install its only
non-stdlib dependency with `python3 -m pip install pyserial`.

When a serbridge (`../../retrosim-transports/serbridge/README.md#sharing-the-port-rfc-2217`)
started with `--listen` holds the port, the tool opens it through the bridge
over RFC 2217 instead (`tools/bridgeport.py`, a copy of
`retrosim-transports/serbridge/clients/python/bridgeport.py`): the bridge's log
keeps the whole capture, including what the board says before and after, and
other tools can watch the line. With no bridge the port is opened directly.
DTR and RTS are held low either way.

```sh
python3 ../retrosim-build/tools/uart_prog_capture.py \
  --port PORT --timeout 90 --marker "SD(4-bit)" \
  --expect "P=1 E=0 EC=0" --expect "MV=1" \
  --expect "STR n=32768" --expect "ok=1 errs=00000 e=0c0" \
  --cwd fpga -- "C:/Program Files/Git/bin/bash.exe" \
  build.sh a7lite sd4 prog
```

The programming command follows `--` and is executed directly, without an
intermediate shell. Use an absolute Git Bash path on Windows when the repo's
`build.sh` is the programmer entry point; a bare `bash` may resolve to WSL.

## 6. Verification

The host unit tests exercise parsing, tool selection, failed-child propagation,
stale receipts, cache invalidation, coverage input selection, policy validators
and programming preflight. Tcl primitives use mocked vendor commands in a
headless interpreter. Consumers exercise the build helpers through their own lint,
simulation, and vendor-build gates. A passing host test does not establish
timing closure or hardware behavior for a consumer.
