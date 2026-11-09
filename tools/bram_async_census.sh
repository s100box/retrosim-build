#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# ============================================================================
# bram_async_census.sh -- run the REQP-1839/1840 census over a repo's design.
#
#   bram_async_census.sh <fpga-dir-with-build.tcl> [top]
#   bram_async_census.sh --files "<a.sv b.sv ...>" --top <mod> [--name <label>]
#
# The first form reads a Gowin gw_sh build.tcl -- the file list and top module
# are already stated there as `add_file -type verilog <path>` and
# `set_option -top_module <mod>`, so a Gowin-only repo can be checked against a
# VIVADO rule without acquiring a Vivado target. Lines whose path is a Tcl
# variable (the per-board PLL wrappers, chosen by env var) are skipped: they are
# vendor primitives that black-box anyway.
#
# Runs from the build.tcl's own directory, so the relative paths and $readmemh
# images resolve exactly as they do for the real build.
# ============================================================================
set -uo pipefail

lib="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
. "$lib/vivado.sh"
vivado_require || exit $?

files=""; top=""; name=""; dir="."; extra=""
if [ "${1:-}" = "--files" ]; then
  files="$2"; shift 2
  while [ $# -gt 0 ]; do
    case "$1" in
      --top)  top="$2";  shift 2 ;;
      --name) name="$2"; shift 2 ;;
      *) echo "unknown arg $1" >&2; exit 2 ;;
    esac
  done
else
  dir="${1:?usage: bram_async_census.sh <fpga-dir> [top] [extra-files...]}"
  tcl="$dir/build.tcl"
  # Anything after the top is prepended verbatim. A per-board file that appears
  # in build.tcl as a Tcl VARIABLE (`add_file -type verilog $boardpkg`) cannot be
  # resolved from the file alone -- build.sh picks it per board. Most are PLL
  # wrappers full of vendor primitives and are no loss as black boxes, but a
  # board *package* is real RTL the design will not elaborate without.
  extra="${*:3}"
  [ -f "$tcl" ] || { echo "no $tcl" >&2; exit 2; }
  # add_file -type verilog <path>   (skip $variable paths -- per-board PLLs)
  files="$(grep -E '^[[:space:]]*add_file[[:space:]]+-type[[:space:]]+verilog' "$tcl" \
           | sed -E 's/.*add_file[[:space:]]+-type[[:space:]]+verilog[[:space:]]+//' \
           | tr -d '\r' | grep -v '\$' | tr '\n' ' ')"
  files="$extra $files"
  top="${2:-$(grep -E '^[[:space:]]*set_option[[:space:]]+-top_module' "$tcl" \
              | sed -E 's/.*-top_module[[:space:]]+//' | tr -d '\r' | head -1)}"
  name="${name:-$(cd "$dir/.." && basename "$(pwd)")}"
fi
[ -n "$files" ] || { echo "no source files found" >&2; exit 2; }
[ -n "$top" ]   || { echo "no top module found" >&2; exit 2; }
name="${name:-$top}"

log="$(mktemp -t census.XXXXXX)"
( cd "$dir" && CENSUS_FILES="$files" CENSUS_TOP="$top" CENSUS_NAME="$name" \
    "$VIVADO" -mode batch -nojournal -nolog -notrace \
      -source "$lib/tools/bram_async_census.tcl" ) > "$log" 2>&1
grep -E '^(RESULT|census:|   )' "$log" || {
  echo "RESULT $name : SKIPPED (vivado produced no verdict; see $log)"; exit 0; }
# Keep the transcript whenever the verdict was not a clean measurement -- a
# SKIPPED line without the synthesis errors behind it is unactionable.
if grep -qE '^RESULT .* (SKIPPED|INCONCLUSIVE)' "$log"; then
  echo "   (transcript kept: $log)"
  grep -E '^ERROR' "$log" | head -5 | sed 's/^/   /'
else
  rm -f "$log"
fi
