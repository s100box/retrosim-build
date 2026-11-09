# Release RTL style

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

[README](../README.md) · [Host setup](host-build-tools.md)

## 1. Shared formatting

The canonical [Verible formatter profile](../templates/verible.format) uses
100 columns, two-space indentation and four-space continuation wrapping.
Assignments, port declarations, named ports and named parameters align.
Consumers keep a local `.verible.format` copy so their ordinary lint commands
work from a standalone checkout with the documented build sibling.

From the workspace root, compare the release projects with:

```sh
python retrosim-build/tools/check_verible_style.py hh-uart hh-hdmi hh-emac hh-sdcard mega138kpro-sfp hh-xcku5p-dev hh-rk-zynq7100-dev --allow-unconfigured
```

The checker compares effective settings and rejects duplicates and unexplained
lint exceptions. It does not lint RTL. `UNCONFIGURED` explicitly identifies a
repository with no profile; it fails unless `--allow-unconfigured` is supplied.
Use each project's documented lint/format command to check source conformance.

## 2. Lint policies and checked scope

Verible defaults are the baseline. Keep justified consumer exceptions local;
copying every consumer's waivers into a common set would weaken unrelated gates.

| Project | Lint scope | Local differences from defaults |
|---|---|---|
| `hh-uart` | RTL, benches and formal property files | None. |
| `hh-hdmi` | RTL, PLL wrappers, formal properties/clock driver and EDID probe; formatting also checks benches | Uppercase localparams: `-parameter-name-style`. |
| `hh-emac` | RTL, SoC and FPGA wrappers; formatting checks tracked `.sv` files | Uppercase localparams; untyped string parameters for Icarus compatibility. |
| `hh-sdcard` | Ninja's listed RTL and model/bench inputs | Uppercase localparams; untyped string parameters for Icarus compatibility. |
| `mega138kpro-sfp` | First-party RTL; formatting also checks benches | Uppercase localparams; blocking assignments allowed for block-local `always_ff` temporaries. |
| `hh-xcku5p-dev` | Every tracked `.sv` file: board RTL, benches, models and primitive stubs (`pl/sim/lint.sh`, run by the commit hook) | Uppercase localparams; file-scoped waivers for the UNISIM stubs, the GTY IP model's module name and the board top's bus-connection macro. |
| `hh-rk-zynq7100-dev` | No Verible gate | Icarus, top elaboration, optional Verilator lint and Yosys checks; Verible adoption remains pending. |

`retrosim-core` and `retrosim-transports` use Rust formatting/Clippy, not Verible.
`retrosim-build` supplies tooling and templates rather than a consumer RTL tree.

The active formatter settings agree. Naming and language-compatibility exceptions
are explicit, rather than claims that all lint profiles or checked file sets are
identical. `hh-rk-zynq7100-dev` still needs Verible adoption before claiming
the same lint and format coverage as the core projects. `hh-xcku5p-dev` already
checks every tracked `.sv` file. Generated/vendor IP and legacy Verilog require
an explicit scope decision when extending the gates.

## 3. Gate behavior

`--inplace --verify` checks multiple files without rewriting them; use `--inplace`
alone to apply formatting. The shared tool pin selects the Verible installation.
Some consumer scripts skip missing tools, as their READMEs explain; a skipped
check is not evidence of source conformance. Release validation must record
which tools and file sets actually ran.
