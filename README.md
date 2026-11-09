# retrosim-build

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

Shared build, test, timing, and programming infrastructure for FPGA projects.
Check this repository out beside its consumers; they use its files by relative
path without copying them.

## Documentation

| Document | Contents |
|---|---|
| [Design](doc/retrosim-build-design.md) | Components, consumer conventions, freshness checks, and timing sign-off. |
| [Documentation conventions](doc/documentation-style.md) | Shared README structure, design style, and information ownership. |
| [Host services](doc/host-services.md) | Manifest benches, coverage, build snapshots, programming, validation and Tcl APIs. |
| [RTL tooling integration](doc/rtl-tooling-review.md) | Consumer inventory, shared-service boundaries and validation scope. |
| [Host setup](doc/host-build-tools.md) | Tool installation and host environment. |
| [Verilator/MSVC helper](tools/verilator_msvc/README.md) | Native Windows simulation builds. |
| [Console flash map](doc/console138k-flash-map.md) | Flash regions and programming constraints. |
| [VAX toolchain](doc/vax-binutils-windows.md) | Build instructions and validation. |
| [RTL style](doc/rtl-style.md) | Shared formatting, local lint exceptions, and checked scope. |

## Repository layout

| Path | Contents |
|---|---|
| `toolchain.ninja`, `toolchain.ps1` | Shared tool locations and environment. |
| `gowin.sh`, `vivado.sh`, `vivado.tcl`, `fpga_common.sh` | FPGA build and programming helpers. |
| `tools/` | Timing, project generation, simulation, coverage, and capture tools. |
| `hooks/` | Shared commit-hook environment and checks. |
| `templates/`, `WORKFLOW-TEMPLATE.md` | Consumer configuration templates. |
| `tests/` | Host-side unit tests. |

## Requirements

### Tools

Install only the tools required by the consuming project. Ninja reads
`toolchain.ninja`; shell and PowerShell drivers also accept environment
overrides. [Host setup](doc/host-build-tools.md) covers the supported Windows
environment and tool discovery. Python 3.10 or later runs the shared host services
and hook checks; serial capture
also needs pyserial.

### Sibling repositories

There is no required RTL sibling for the shared helpers. Each consumer
declares its own dependencies. Optional tool builders require the source
repositories named in their individual documentation.

## Getting started

1. Clone this repository beside the consuming project.
2. Set the tool roots in [toolchain.ninja](toolchain.ninja) for your installation.
3. Follow the consumer's README for its build and simulation targets.

Build-script interfaces vary by consumer. The
[consumer conventions](doc/retrosim-build-design.md#3-consumer-conventions)
describe the shared verbs and board selection rules; the
[component reference](doc/retrosim-build-design.md#2-components) identifies
the helper for each task.

## Verification

From the repository root:

```sh
python -m unittest discover -s tests
```

These tests exercise the RTL-name parser, tool discovery, process verdicts,
build/cache receipts, coverage selection, programming preflight and policy
validators. Tcl primitive tests require Python's `tkinter` module and run headless.
Consumers also run their own lint, simulation and vendor-build gates.

## License

Licensed under either [MIT](LICENSE-MIT) or [Apache-2.0](LICENSE-APACHE), at your option.
Shared-service extraction sources are recorded in [FORKED.md](FORKED.md).
