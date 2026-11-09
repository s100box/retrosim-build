# Host build tools — Windows setup

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

Install the tools needed by the projects you intend to build, then configure
[toolchain.ninja](../toolchain.ninja). Each consumer's README specifies its
requirements and gate commands. The shared pin contains editable Windows paths;
for a POSIX host, set the relevant roots and `bash_exe` to native tools.

## Tool inventory

| Tool | Tested version or interface | Purpose |
|---|---|---|
| Git for Windows | Git Bash | shell scripts on Windows |
| Python | 3.10 or later for shared services and hook checks; consumers may require a newer version | generators, host tools and report checkers |
| Ninja | 1.10 or later for the board/core projects | lint and simulation dispatch |
| Verible | v0.0-4053-g89d4d98a | SystemVerilog syntax, lint and formatting |
| OSS CAD Suite | Icarus 14.0, Verilator 5.049, Yosys 0.65 | simulation, coverage and optional synthesis/formal checks |
| Visual Studio | C++ tools and bundled CMake/Ninja | native Verilator harnesses and MSVC Rust crates |
| Gowin EDA | V1.9.12.03 | synthesis, IP generation and programming |
| AMD Vivado | 2026.1 for XCKU5P and RK-ZYNQ7100 | synthesis, IP generation and programming; install the appropriate device support |
| Rust / Cargo | consumer's Cargo.toml requirements | host applications and model-based tests |
| cc65 | V2.19 | 6502 assembly/ROM projects |
| asm6809 | 2.17 | 6809 assembly/ROM projects |
| GHDL | 6.0.0, mcode/mingw64 | VHDL benches |
| SDCC | 4.6.0 host release; 4.6.2 fork with -mm6809 | firmware; check the consumer for native versus WSL invocation |
| MSYS2 MinGW64 | native compiler, make, bison and flex | native SDCC and VAX binutils builds |
| WSL / Linux | Ubuntu 24.04 is a tested host | Buildroot and consumers that invoke Linux-built SDCC tools |

The core-only XCKU5P build does not need the CPU, firmware or Rust dependencies
used by the standalone hh-emac and hh-sdcard demonstration systems.

## Environment

Keep tool paths in the shared pin. Shell resolvers accept environment overrides
and fall back to discovery; PowerShell consumers dot-source
[toolchain.ps1](../toolchain.ps1). Ninja includes the pin directly, so edit its
root assignments for your installation before invoking Ninja.

Typical shell overrides are `GWSH`, `PROGRAMMER_CLI`, `OSS_CAD_SUITE`,
`VERIBLE_ROOT` and `VIVADO`. PowerShell also exports compiler roots from the pin.
See each resolver for precedence and supported discovery paths.

For an interactive Git Bash simulation session:

```sh
oss="$(cygpath -u "$USERPROFILE")/oss-cad-suite"
export OSS_CAD_SUITE="$oss"
export PATH="$oss/bin:$oss/lib:$PATH"
```

Both bin and lib are needed for the OSS CAD Suite DLLs on Windows.
[hooks/gate-env.sh](../hooks/gate-env.sh) prepares this environment for hooks.
Keep Gowin's Qt/DLL directories out of the global PATH; gowin.sh invokes its
executables by path and clears QT_PLUGIN_PATH.

## Build entry points

| Work | Entry point |
|---|---|
| Core lint and simulation | consumer's sim/ Ninja targets or gate scripts |
| Gowin builds | consumer's fpga/build.sh, sourcing gowin.sh |
| Vivado builds | consumer's build script or batch Tcl; XCKU5P uses vivado.sh |
| Verilator with MSVC | tools/vl_build.ps1, tools/vl_cov.ps1, or tools/verilator_msvc.py |
| Host binary-analysis tools | tools/build-dasm-tools.sh [all\|dasmxx\|macro11] [--clean] [--test] |
| Native VAX binutils | [build and verification procedure](vax-binutils-windows.md) |
| SDCC m6809 fork | sibling sdcc-6809/tools/installer/build-msys2.sh for Windows; the fork's regression instructions for WSL |

Run lint before simulation and the consumer's simulation gate before synthesis.
Vendor synthesis and hardware tests remain separate checks; passing a software
gate does not establish timing closure or board operation.

## Windows troubleshooting

1. **Use LF for scripts executed under Linux.** Clone Linux-built sources with
   `git -c core.autocrlf=false clone <repository-url>`. Preserve local work when
   correcting an existing checkout's line endings.
2. **SDCC can be installed per-user.** If its installer requests elevation,
   extract it with 7-Zip into a chosen tools directory, then set the shared pin.
3. **Missing DLLs can make Icarus or Verilator exit without useful output.**
   Put the matching OSS CAD Suite bin and lib ahead of Git's DLL directories.
4. **Use an explicit Git Bash path in Windows Ninja rules.** A bare bash can
   resolve to the WSL launcher in System32. Include toolchain.ninja and invoke
   `$bash_exe`. Projects with a POSIX-default build.ninja may provide wninja,
   wninja.cmd and _win.ninja; follow their README. Ninja does not accept
   Make-style variable overrides as command arguments.
5. **Use the shared MSVC driver for native Verilator builds.** It imports the
   Visual Studio amd64 environment and uses its bundled CMake/Ninja. Set
   VERILATOR_ROOT to the suite's share/verilator if overriding discovery.
   The verilator launcher also needs Perl; verilator_bin.exe is native.
6. **Serialize Gowin operations.** Do not overlap gw_sh with another synthesis
   or with programmer_cli. The wrapper manages its own synthesis lock, but
   manually launched vendor tools can still contend for resources.
7. **Discover cable locations.** programmer_cli --location identifies a host
   USB connection, not a board model. Use --scan-cables, verify the device with
   --scan --location <N>, then set PROGDEV for that session.
8. **Install the debugger's USB driver.** An FT2232 Sipeed debugger needs the
   FTDI VCP/D2XX driver. An unknown USB device, no UART port, or no cables from
   programmer_cli --scan-cables can indicate a missing driver. Reconnect the
   board after installation.
9. **Match the compiler to the consumer.** MSVC backs native C++ harnesses and
   Rust's MSVC target. Linux SDCC binaries require WSL/Linux; installing a
   Windows compiler does not change a script that explicitly invokes a
   sibling's Linux binary.
