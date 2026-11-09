#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# vivado.sh -- the shared Xilinx/AMD build+program library for the retrosim
# FPGA repos. The exact counterpart of gowin.sh; SOURCED (not executed) by
# each repo's fpga/build.sh:
#
#   lib="../../retrosim-build/vivado.sh"
#   [ -f "$lib" ] || { echo "missing ../retrosim-build sibling (check it out beside this repository)"; exit 1; }
#   . "$lib"
#
#   vivado_board <board>      # resolve the board table (see below)
#   vivado_synth <tcl>        # vivado -mode batch -source <tcl>, then gate
#   vivado_prog <base>        # volatile JTAG load of impl_<base>/<base>.bit
#   vivado_prog_flash <base>  # persistent QSPI program+verify of the .mcs
#
# vivado_board sets: VIVADO_BOARD (canonical name), VIVADO_PART (full
# part-speed string for synth_design -part), VIVADO_CFGMEM (the
# get_cfgmem_parts pattern for the onboard config flash), VIVADO_CLK_HZ (the
# board oscillator), VIVADO_TARGET (a get_hw_targets filter, or "" for "the
# only one attached").
#
# Environment: VIVADO (the vivado launcher, default `vivado`), VIVADO_TARGET
# (overrides the board table when several JTAG pods are attached -- find yours
# with `vivado -mode batch -source <tools/vivado_scan.tcl>`).
#
# The timing sign-off is NOT here: unlike Gowin (whose report has to be
# scraped out of HTML by tools/timing_signoff.py), Vivado exposes WNS/WHS as
# first-class Tcl properties, so each repo's build tcl gates inline and
# `error`s out -- which lands here as a nonzero exit.

VIVADO_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$VIVADO_LIB_DIR/fpga_common.sh"

# $VIVADO wins; then the workspace toolchain pin (toolchain.ninja:
# vivado_root -- set it on hosts with Vivado so a version bump edits ONE
# file); then the PATH; then the standard install root. Unlike the Gowin
# tools (whose version choice is a correctness question -- see the workspace
# rule against the Education edition), any recent Vivado builds these
# designs, so falling back to the newest installed one is safe and saves
# every caller a settings64 sourcing.
# A set-but-DEAD absolute path (a long-running shell that predates a
# reinstall) falls through with a warning -- the same contract as gowin.sh.
case "${VIVADO:-}" in
  */* | *\\*)
    if [ ! -f "$VIVADO" ] && [ ! -f "$(echo "$VIVADO" | tr '\\' '/')" ]; then
      echo "vivado.sh: ignoring stale VIVADO ($VIVADO does not exist); re-resolving" >&2
      VIVADO=""
    fi ;;
esac
VIVADO="${VIVADO:-}"
VIVADO="${VIVADO//\\//}"
if [ -z "$VIVADO" ]; then
  _vv_root="$(sed -n 's/^vivado_root *= *//p' "$VIVADO_LIB_DIR/toolchain.ninja" 2>/dev/null | head -1)"
  if [ -n "$_vv_root" ] && [ -f "$_vv_root/bin/vivado.bat" ]; then
    VIVADO="$_vv_root/bin/vivado.bat"
  fi
  unset _vv_root
fi
if [ -z "${VIVADO:-}" ]; then
  if command -v vivado >/dev/null 2>&1; then
    VIVADO="vivado"
  else
    # Spell out GNU sort's path. In some non-interactive Git-Bash sessions,
    # System32 precedes /usr/bin and Windows sort.exe wins command lookup; it
    # rejects `-r`, leaving this pipeline empty even though Vivado is installed.
    for _v in $(ls -d /c/AMDDesignTools/*/Vivado/bin/vivado.bat \
                     /c/Xilinx/Vivado/*/bin/vivado.bat 2>/dev/null | /usr/bin/sort -r); do
      VIVADO="$_v"; break
    done
    unset _v
  fi
fi
VIVADO="${VIVADO:-vivado}"

# ---- "is Vivado on this machine at all?" ----------------------------------
# Vendor-free simulation remains usable without Vivado. Distinguish an
# absent toolchain from a synthesis failure with an explicit probe.
#
#   vivado_available   quiet predicate; 0 = usable, 1 = absent
#   vivado_require     one actionable message + return 127 (the shell's own
#                      "command not found" code, so a caller or CI can tell
#                      "tool absent, skip" apart from "build failed, fix it")
vivado_available() {
  # An absolute path must exist; a bare name must resolve on PATH.
  case "$VIVADO" in
    */*) [ -x "$VIVADO" ] || [ -f "$VIVADO" ] ;;
    *)   command -v "$VIVADO" >/dev/null 2>&1 ;;
  esac
}

vivado_require() {
  vivado_available && return 0
  cat >&2 <<EOF
⛔ Vivado not found — this step needs the Xilinx toolchain and will be skipped.
   Looked for: \$VIVADO ('$VIVADO'), 'vivado' on PATH, then
   /c/AMDDesignTools/*/Vivado/bin/vivado.bat and /c/Xilinx/Vivado/*/bin/.
   Point VIVADO= at your install if it lives elsewhere.

   ⓘ This is NOT a build failure and nothing is wrong with the design.
   Everything that gates correctness runs WITHOUT Vivado: the Rust model,
   the Verilator/iverilog sim gates, and the commit hooks. Only bitstream
   synthesis and board programming need it.
EOF
  return 127
}

# The one board table.
vivado_board() {
  case "$1" in
    a7lite | a7_lite | microphase_a7lite)
      VIVADO_BOARD="a7lite"
      VIVADO_PART="xc7a200tfbg484-2"
      VIVADO_CFGMEM="is25lp128f-spi-x1_x2_x4"
      VIVADO_CLK_HZ=50000000
      # Onboard Digilent-compatible FT2232H JTAG; one pod, so no filter.
      VIVADO_TARGET="${VIVADO_TARGET:-}"
      ;;
    z7nano | z7_nano | microphase_z7nano)
      VIVADO_BOARD="z7nano"
      VIVADO_PART="xc7z020clg400-2"
      # W25Q128JVSIQ. Listed for completeness and UNTESTED: on a Zynq the PL is
      # configured by the PS, so the production path is Linux loading the
      # bitstream through the FPGA manager, not a QSPI cfgmem image. Note the
      # vendor's own table says "128M Byte" for this part; a W25Q128 is 128
      # Mbit = 16 MByte.
      VIVADO_CFGMEM="w25q128jv-spi-x1_x2_x4"
      VIVADO_CLK_HZ=50000000
      # PL oscillator U3 on N18. The PS has its own 33.333 MHz on E7, which is
      # not this and is not visible to the fabric.
      VIVADO_TARGET="${VIVADO_TARGET:-}"
      ;;
    xcku5p | xcku5p_dev | hh_xcku5p_dev)
      # The unbranded XCKU5P development board (../hh-xcku5p-dev). Its guide
      # is the source for every value here: the 1.8V Master SPI flash, an
      # MT25QU128 (the schematic says MT25QU256, but the fitted chip reads
      # as a 128 and program_hw_cfgmem refuses the 256 entry), the x1_x2_x4
      # entry (an x8 entry means two chips), the 50 MHz U1 oscillator on E18,
      # and one FT232HQ JTAG channel behind the USB hub.
      VIVADO_BOARD="xcku5p"
      VIVADO_PART="xcku5p-ffvb676-2-i"
      VIVADO_CFGMEM="mt25qu128-spi-x1_x2_x4"
      VIVADO_CLK_HZ=50000000
      VIVADO_TARGET="${VIVADO_TARGET:-}"
      ;;
    *)
      echo "unknown Xilinx board '$1' (a7lite, z7nano, xcku5p)" >&2
      return 2 ;;
  esac
}

# vivado_run <tcl> [tclargs...] -- batch Vivado with the noise filtered and
# the exit status preserved through the pipe.
# The FULL transcript always lands in $VIVADO_LOG (default vivado_build.log in
# the caller's cwd) even though the console view is filtered. A Vivado run on a
# large design is minutes to an hour; re-running one just to see an error that
# slipped past a grep is the kind of waste that adds up fast.
vivado_run() {
  local tcl="$1"; shift
  local rc log="${VIVADO_LOG:-vivado_build.log}"
  # Say "the tool is missing" before producing an empty log that says
  # nothing. Returns 127 so callers can skip rather than fail.
  vivado_require || return $?
  set -o pipefail
  "$VIVADO" -mode batch -nojournal -nolog -notrace -source "$tcl" \
      ${1+-tclargs "$@"} 2>&1 \
    | tee "$log" \
    | grep -vE '^\s*$|^INFO: \[(Common 17-(14|1540)|Vivado_Tcl|Netlist|Project 1-)' \
    | grep --color=always -E '^|ERROR|CRITICAL WARNING|TIMING FAILED|achieved Fmax'
  rc=${PIPESTATUS[0]}
  [ $rc -ne 0 ] && echo "vivado: full transcript in $log" >&2
  return $rc
}

# vivado_synth <tcl> -- run the repo's build tcl (which reads the exported env
# vars, implements, gates timing, and writes the .bit/.mcs).
vivado_synth() {
  local tcl="${1:-build_vivado.tcl}" rc
  [ -f "$tcl" ] || { echo "missing $tcl" >&2; return 1; }
  vivado_run "$tcl"; rc=$?
  [ $rc -eq 0 ] && return 0
  # ⚠ 127 = the toolchain is absent (vivado_require already said so, with
  # the "nothing is wrong with your design" note). Do NOT relabel it
  # "build FAILED" — that is the misreading this distinction exists to
  # prevent. Anything else is a genuine build failure.
  [ $rc -eq 127 ] || echo "vivado build FAILED" >&2
  return $rc
}

# vivado_prog <base> -- volatile SRAM configuration over JTAG.
vivado_prog() {
  local bit="impl_$1/$1.bit"
  # Toolchain first: on a machine without Vivado the .bit cannot exist
  # either, and "missing impl_x/x.bit -- build it first" would send the
  # reader off to run a build that also cannot work.
  vivado_require || return $?
  [ -f "$bit" ] || { echo "missing $bit -- build it first" >&2; return 1; }
  # The shared freshness gate (fpga_common.sh): prog NEVER builds, so refuse
  # a .bit older than the RTL/constraints. ALLOW_STALE_BITSTREAM=1 overrides.
  retrosim_fs_freshness "$bit" || return 3
  VIVADO_BIT="$(cd "$(dirname "$bit")" && pwd)/$(basename "$bit")" \
  VIVADO_MODE="sram" \
  VIVADO_HW_TARGET="$VIVADO_TARGET" \
    vivado_run "$VIVADO_LIB_DIR/tools/vivado_prog.tcl"
}

# vivado_prog_flash <base> [mcs] -- persistent QSPI program + verify.
#
# The optional second argument programs an MCS other than the build's own.
# That is what makes a data-region write possible: vivado_prog.tcl sets
# PROGRAM.ADDRESS_RANGE to use_file, so an MCS built with only a -loaddata
# region erases and writes ONLY the sectors that region covers and leaves the
# bitstream at 0x0 alone -- the Vivado equivalent of programmer_cli's
# --spiaddr, and what a "swap the diagnostic without a resynth" flow needs.
# A third argument of 0 suppresses the post-program boot-from-flash, which is
# only meaningful when the MCS carries a bitstream at address 0.
vivado_prog_flash() {
  local mcs="${2:-impl_$1/$1.mcs}"
  local boot="${3:-1}"
  vivado_require || return $?
  [ -f "$mcs" ] || { echo "missing $mcs -- build it first" >&2; return 1; }
  # Freshness-gate ONLY the build's own MCS: an explicit second argument is a
  # data-region image (a diagnostic/ROM payload), not a product of the RTL,
  # and gating it against source timestamps would cry wolf.
  if [ -z "${2:-}" ]; then
    retrosim_fs_freshness "$mcs" || return 3
  fi
  VIVADO_MCS="$(cd "$(dirname "$mcs")" && pwd)/$(basename "$mcs")" \
  VIVADO_MODE="flash" \
  VIVADO_CFGMEM_PART="$VIVADO_CFGMEM" \
  VIVADO_CFGMEM_BOOT="$boot" \
  VIVADO_HW_TARGET="$VIVADO_TARGET" \
    vivado_run "$VIVADO_LIB_DIR/tools/vivado_prog.tcl"
}
