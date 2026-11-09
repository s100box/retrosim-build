# Shared-service provenance

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

The host services consolidate first-party build mechanics from sibling projects.
All listed source projects license this original tooling under MIT OR Apache-2.0.
Consumer policy remains in those repositories; no CPU implementation is included
in these extractions.

| Shared implementation | Source and boundary |
|---|---|
| Manifest execution and coverage | `hh-xcku5p-dev/pl/sim` and `hh-rk-zynq7100-dev/pl/sim`: argument lists, logging and coverage lifecycle; source lists and verdicts remain local. |
| Native build snapshots | `hh-unibus/sim/vl`, `hh-j11/sim/vl` and `hh-c128/sim/vl`: CMake snapshot and executable publication mechanics; consumer CMake projects remain local. |
| External programming adapter | `tvi995/fpga/tvi990_hdmi_tang20k/tools/flash.ps1`: explicit artifact location and cable interface; operations and timing checks use the shared Gowin implementation. |
| Tree and citation engines | The seven `z7nano-sst-*` consumer checkers identified in the [integration review](doc/rtl-tooling-review.md#shared-service-migrations): text/link/SPDX and numbered-authority validation; exclusions and attribution policy remain local. |
| Vivado primitives | Six Z7 rig `syn/build_vivado.tcl` flows and RK project setup: project creation, IP reuse, port and latch checks; board-specific IP and synthesis policy remain local. |
