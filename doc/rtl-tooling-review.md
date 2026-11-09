# RTL tooling integration

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

[README](../README.md) · [Shared build contracts](retrosim-build-design.md)

## Scope and ownership

The inventory below covers primary workspace checkouts with tracked HDL,
including ROM projects with RTL test harnesses. Scratch/sign-off worktrees and
vendored implementation bodies are excluded. It records build integration,
not a certification of each consumer's RTL or hardware.

Consumers retain source manifests, timing constraints, board safety policy,
verdict markers and hardware procedures. Shared helpers own tool discovery,
bounded process execution and the services below. Full synthesis, programming
and hardware qualification are separate gates.

## Tool selection

Use the shared pin and explicit environment overrides through the documented
resolvers. Native Windows Ninja entry points use the quoted Git Bash pin;
Linux entry points use native Bash. Primary hooks source `gate-env.sh` before
testing for tools. The RK board hook validates an exported staged tree.
Native simulation shims delegate compiler and Verilator discovery to the shared
driver. Per-run summaries and coverage merges consume explicit current-run
inputs so stale logs cannot satisfy a new run.

<a id="shared-service-migrations"></a>
## Shared services

The shared implementations and public contracts are documented in
[Host services](host-services.md). Consumers execute the sibling tools directly.

| Service | Implementation | Consumers |
|---|---|---|
| Integration checker | `tools/audit_consumers.py`, primary-hook bootstrap | All consumers sourcing the shared primary-hook environment |
| Formal suite runner | `tools/formal_suite.py`, consumer proof manifests | UART, HDMI, EMAC and SD-card proofs, covers and negative controls |
| Manifest bench runner | `tools/bench_suite.py`, consumer JSON manifests | XCKU5P and RK-ZYNQ7100 board benches |
| External-artifact programming | `tools/program_fpga.py`, canonical Gowin dispatcher | TVI-990 prototype wrapper, with freshness and timing preflight |
| CMake Verilator integration | `tools/verilator.cmake` | Native builder and UART, HDMI, EMAC, SD-card and Mega coverage projects |
| Native build snapshots | `tools/vl_build.ps1`, content-bound snapshot driver | UNIBUS, J11 and C128 native bench shims |
| Host-neutral coverage | Manifest coverage, `tools/coverage_merge.py`, `tools/run_logged.py` | XCKU5P, RK-ZYNQ7100 and Zilog coverage drivers |
| Tree and citation validation | Policy-driven shared Python engines | Seven Z7 rig tree checks; five rig citation checks |
| Python toolchain resolver | `tools/retrosim_build/toolchain.py` | Shared services, native bench builder and NVAX development receipts |
| Vivado Tcl primitives | `vivado.tcl` project, IP cache, port and latch procedures | Six Z7 rig build flows and RK board/DDR project setup |

Project source lists, hardware checks, verdict markers and numbered authorities
remain consumer-owned. IP reuse is content-bound; coverage merges use explicit
current-run inputs. CMake consumers and in-tree programming entry points keep
their own interfaces.

## Repository inventory

The helper column records direct shared references found in build metadata;
indirect references through local wrappers may add further integration. Public
repositories are linked; other rows identify sibling workspace checkouts.

| Repository | Shared helper families |
|---|---|
| `6502-bench` | toolchain/environment, Gowin |
| `a2600box` | toolchain/environment, Gowin, coverage, constraints, project generation |
| `basic6502` | Repository-owned harness, shared hook environment |
| `basic6809` | Repository-owned harness, shared hook environment |
| `hdmi-tester` | toolchain/environment, Gowin, Vivado, coverage, constraints, project generation |
| `hh-286` | toolchain/environment, Gowin |
| `hh-5160` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-6502` | toolchain/environment, Gowin, MSVC/Verilator, coverage, constraints, project generation |
| `hh-6809` | toolchain/environment, Gowin, Vivado, constraints, project generation |
| `hh-80386` | toolchain/environment, Gowin, MSVC/Verilator |
| `hh-8051` | toolchain/environment, Gowin, MSVC/Verilator, coverage, constraints, project generation |
| `hh-8087` | toolchain/environment, Gowin, MSVC/Verilator |
| `hh-basic` | Repository-owned harness, shared hook environment |
| `hh-c128` | toolchain/environment, Gowin, constraints, project generation |
| `hh-emac` | toolchain/environment, Gowin, Vivado, coverage, constraints |
| [hh-hdmi](https://github.com/s100box/hh-hdmi/blob/main/README.md) | toolchain/environment, coverage |
| `hh-j11` | toolchain/environment, Gowin, Vivado, MSVC/Verilator, constraints |
| `hh-lsi11` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-m68k` | toolchain/environment, Gowin, constraints, project generation |
| `hh-nvax` | toolchain/environment, Vivado, MSVC/Verilator |
| `hh-panel` | toolchain/environment, Gowin, constraints, project generation |
| `hh-pet8032` | toolchain/environment, Gowin, constraints, project generation |
| `hh-rk-zynq7100-dev` | toolchain/environment, manifest benches/coverage, Vivado Tcl |
| `hh-scp8086` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-sdcard` | toolchain/environment, Gowin, Vivado, MSVC/Verilator, coverage, constraints, project generation |
| `hh-sdram` | toolchain/environment, Gowin, Vivado, MSVC/Verilator, coverage, constraints, project generation |
| `hh-spiflash` | toolchain/environment, coverage |
| `hh-tx0` | toolchain/environment, Gowin, constraints |
| `hh-uart` | toolchain/environment, coverage |
| `hh-unibus` | toolchain/environment, MSVC/Verilator |
| `hh-usbh` | toolchain/environment, Gowin, MSVC/Verilator, constraints, project generation |
| `hh-v1170` | toolchain/environment, MSVC/Verilator, constraints |
| `hh-v20` | toolchain/environment, Gowin, MSVC/Verilator |
| `hh-vax` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-vic20` | toolchain/environment, Gowin, constraints, project generation |
| `hh-x86` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-xcku5p-dev` | toolchain/environment, Vivado, manifest benches/coverage |
| `hh-z180` | toolchain/environment, Gowin, MSVC/Verilator |
| `hh-z80` | toolchain/environment, Gowin, Vivado, MSVC/Verilator |
| `hh-z80dbg` | toolchain/environment, MSVC/Verilator |
| `mcs51-bench` | toolchain/environment, Gowin, MSVC/Verilator |
| [mega138kpro-sfp](https://github.com/s100box/mega138kpro-sfp/blob/main/README.md) | toolchain/environment, Gowin, coverage |
| `retrosim-rig` | toolchain/environment |
| `ts804fpga` | toolchain/environment, Gowin, MSVC/Verilator, constraints, project generation |
| `tvi950` | toolchain/environment, Gowin, coverage |
| `tvi995` | toolchain/environment, Gowin, constraints |
| `vt525sim` | toolchain/environment, Gowin, MSVC/Verilator |
| `z7nano-sst-286` | toolchain/environment, Vivado |
| `z7nano-sst-6502` | toolchain/environment, Vivado, MSVC/Verilator |
| `z7nano-sst-6809` | toolchain/environment, Vivado, MSVC/Verilator |
| `z7nano-sst-dcj11` | toolchain/environment, Vivado, MSVC/Verilator |
| `z7nano-sst-fpj11` | toolchain/environment, Vivado, MSVC/Verilator |
| `z7nano-sst-x86` | toolchain/environment, Vivado, MSVC/Verilator |
| `z7nano-sst-zilog` | toolchain/environment, Vivado |

## Validation boundaries

The shared host tests cover stale/live tool roots, quoted paths, failed-child
propagation, bounded execution, stale receipts, cache invalidation, programming
refusal and copy failure. Tcl tests mock vendor commands. Consumer gates add
Ninja graph checks, script parsing, HDL simulation, elaboration and lint.
Coverage and vendor synthesis remain explicit consumer commands.

The shared `retrosim_verilate` wrapper refreshes JSON-derived C++ source lists
and tracks included HDL changes. The native regression changes a timed bench's
split set in place, checks the rebuilt executable through both build paths,
and rejects invalid HDL. Host tests cover output ownership and quoted paths;
see [native helper verification](../tools/verilator_msvc/README.md#verification).

A passing integration check does not establish timing closure or hardware
behavior. Review each consumer's documented prerequisites and actual gate
results; a skipped tool or advisory failure is not a passing validation.
