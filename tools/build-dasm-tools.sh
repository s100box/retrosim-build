#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# build-dasm-tools.sh -- build the two host binary-analysis tools the retro
# work leans on, from anywhere in the workspace:
#
#   dasmxx    ../dasmxx                                (disassembler suite:
#             6502/6805/6809/8048/8051/8080/8086/8096/Z80/PDP-11/AVR/PIC/...)
#   macro11   ../pdp11-docs/diagnostics/tools/macro11  (Rhialto's fork of
#             Richard Krehbiel's portable MACRO-11 assembler)
#
# They are a pair in practice: dasmxx's dasmpdp11 emits MACRO-11 source and
# macro11 reassembles it, which is what makes "byte-exact" a checkable claim
# (../pdp11-docs/diagnostics/cztuka0/selftest.sh is that round trip).
#
# Usage:
#   bash <ws>/retrosim-build/tools/build-dasm-tools.sh [target] [options]
#
#   target:    all (default) | dasmxx | macro11
#   --clean    delete each build/ directory first (full rebuild)
#   --test     run each tool's gate after building (dasmxx: ctest, 23 tests;
#              macro11: the CZTUKA0 assemble-and-compare round trip)
#   --jobs N   parallel build jobs (default: nproc)
#
# Environment: WS (workspace root; default: this repo's parent), DASMXX_DIR,
# MACRO11_DIR, CMAKE (a specific cmake), VSINSTALL (a specific Visual Studio).
#
# Windows note: macro11 is delegated to its own build-msvc.ps1, which imports
# vcvars and builds with NMake so the exe lands at build/macro11.exe -- the
# path its README and the cztuka0 scripts name. dasmxx is built here with the
# Visual Studio generator (no vcvars needed), so its exes land in
# build/Release/ per that repo's own convention.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="${WS:-$(cd "$HERE/../.." && pwd)}"
DASMXX_DIR="${DASMXX_DIR:-$WS/dasmxx}"
MACRO11_DIR="${MACRO11_DIR:-$WS/pdp11-docs/diagnostics/tools/macro11}"

TARGET=all
CLEAN=0
TEST=0
JOBS="$( (command -v nproc >/dev/null && nproc) || echo 4)"

while [ $# -gt 0 ]; do
  case "$1" in
    all|dasmxx|macro11) TARGET="$1" ;;
    --clean)            CLEAN=1 ;;
    --test)             TEST=1 ;;
    --jobs)             shift; JOBS="${1:?--jobs needs a count}" ;;
    --jobs=*)           JOBS="${1#--jobs=}" ;;
    -h|--help)          sed -n '4,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "build-dasm-tools: unknown argument '$1' (try --help)" >&2; exit 2 ;;
  esac
  shift
done

case "$(uname -s)" in MINGW*|MSYS*|CYGWIN*) IS_WIN=1 ;; *) IS_WIN=0 ;; esac

say() { echo "=== $* ==="; }

# ---- cmake ----------------------------------------------------------------
# On Windows prefer the CMake bundled with Visual Studio: a PATH cmake is
# often older than the installed VS and then does not know its generator
# (for example, CMake 3.30.1 with "Visual Studio 18 2026"), which fails
# configure with nothing but "could not find any instance of Visual Studio".
find_cmake() {
  if [ -n "${CMAKE:-}" ]; then echo "$CMAKE"; return; fi
  if [ "$IS_WIN" = 1 ]; then
    local vs c
    for vs in "${VSINSTALL:-}" \
              "/c/Program Files/Microsoft Visual Studio/18/Insiders" \
              "/c/Program Files/Microsoft Visual Studio/18/Community" \
              "/c/Program Files/Microsoft Visual Studio/2022/Community" \
              "/c/Program Files/Microsoft Visual Studio/2022/Professional"; do
      [ -n "$vs" ] || continue
      c="$vs/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
      [ -x "$c" ] && { echo "$c"; return; }
    done
  fi
  command -v cmake || { echo "build-dasm-tools: no cmake found (set CMAKE)" >&2; exit 1; }
}

CMAKE="$(find_cmake)"
CTEST="$(dirname "$CMAKE")/ctest"
[ -x "$CTEST" ] || [ -x "$CTEST.exe" ] || CTEST="ctest"

# Newest Visual Studio generator this cmake supports, if any. Empty elsewhere,
# which leaves cmake its platform default (Makefiles/Ninja).
GEN="$("$CMAKE" --help 2>/dev/null |
       sed -n 's/^[* ] *\(Visual Studio [0-9][0-9]* [0-9][0-9]*\).*/\1/p' |
       sort -r | head -n1)"

# Visual Studio is multi-config: the build type is chosen at build time, not
# configure time, and the exes land in a per-config subdirectory.
if [ -n "$GEN" ]; then
  CFG_ARGS=(-G "$GEN" -A x64)
  BUILD_ARGS=(--config Release)
  CTEST_ARGS=(-C Release)
  BINSUB="/Release"
else
  CFG_ARGS=(-DCMAKE_BUILD_TYPE=Release)
  BUILD_ARGS=()
  CTEST_ARGS=()
  BINSUB=""
fi

cmake_build() {   # <srcdir> <builddir>
  local src="$1" bld="$2"
  if [ "$CLEAN" = 1 ]; then rm -rf "$bld"; fi
  "$CMAKE" -S "$src" -B "$bld" "${CFG_ARGS[@]}"
  "$CMAKE" --build "$bld" ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} --parallel "$JOBS"
}

# ---- dasmxx ---------------------------------------------------------------
build_dasmxx() {
  [ -f "$DASMXX_DIR/CMakeLists.txt" ] || {
    echo "build-dasm-tools: no dasmxx at $DASMXX_DIR (run 'repo sync dasmxx')" >&2
    exit 1; }
  say "dasmxx: ${GEN:-default generator}"
  cmake_build "$DASMXX_DIR" "$DASMXX_DIR/build"
  if [ "$TEST" = 1 ]; then
    say "dasmxx: ctest"
    "$CTEST" --test-dir "$DASMXX_DIR/build" ${CTEST_ARGS[@]+"${CTEST_ARGS[@]}"} \
             --output-on-failure
  fi
  say "dasmxx OK -> $DASMXX_DIR/build$BINSUB"
}

# ---- macro11 --------------------------------------------------------------
# Sources are fetched, not vendored. build-msvc.ps1 holds the pinned commit;
# read it from there rather than keeping a second copy of the hash in sync.
macro11_fetch() {
  local src="$MACRO11_DIR/src" repo pin
  [ -f "$src/macro11.c" ] && return 0
  repo="$(sed -n "s/^\$repo *= *'\([^']*\)'.*/\1/p" "$MACRO11_DIR/build-msvc.ps1")"
  pin="$( sed -n "s/^\$pin  *= *'\([^']*\)'.*/\1/p" "$MACRO11_DIR/build-msvc.ps1")"
  [ -n "$repo" ] && [ -n "$pin" ] || {
    echo "build-dasm-tools: could not read the macro11 repo/pin out of build-msvc.ps1" >&2
    exit 1; }
  say "macro11: cloning ${repo} @ ${pin:0:8}"
  rm -rf "$src"
  git clone "$repo" "$src"
  git -C "$src" checkout --quiet "$pin"
}

build_macro11() {
  [ -f "$MACRO11_DIR/CMakeLists.txt" ] || {
    echo "build-dasm-tools: no macro11 at $MACRO11_DIR (run 'repo sync pdp11-docs')" >&2
    exit 1; }
  if [ "$CLEAN" = 1 ]; then rm -rf "$MACRO11_DIR/build"; fi

  local exe
  if [ "$IS_WIN" = 1 ]; then
    say "macro11: build-msvc.ps1 (fetch + vcvars + NMake)"
    powershell -ExecutionPolicy Bypass -File "$(cygpath -w "$MACRO11_DIR/build-msvc.ps1")"
    exe="$MACRO11_DIR/build/macro11.exe"
  else
    macro11_fetch
    say "macro11: ${GEN:-default generator}"
    "$CMAKE" -S "$MACRO11_DIR" -B "$MACRO11_DIR/build" -DCMAKE_BUILD_TYPE=Release
    "$CMAKE" --build "$MACRO11_DIR/build" --parallel "$JOBS"
    exe="$MACRO11_DIR/build/macro11"
  fi
  [ -x "$exe" ] || { echo "build-dasm-tools: no macro11 exe at $exe" >&2; exit 1; }

  if [ "$TEST" = 1 ]; then
    # The real gate: assemble a generated image and compare byte-for-byte
    # against the CZTUKA0 XXDP binary. Needs that oracle, which pdp11-oskit
    # fetches -- skip loudly rather than fail when it has not been.
    local self="$MACRO11_DIR/../../cztuka0/selftest.sh"
    local oracle="$WS/hh-v1170/oskit/dl/xxdp-files/ZTUKA0.BIN"
    if [ -f "$self" ] && [ -f "$oracle" ]; then
      say "macro11: CZTUKA0 round trip"
      MACRO11="$exe" ORACLE="$oracle" bash "$self"
    else
      say "macro11: SKIPPED the CZTUKA0 round trip (no oracle at $oracle)"
    fi
  fi
  say "macro11 OK -> $exe"
}

case "$TARGET" in
  dasmxx)  build_dasmxx ;;
  macro11) build_macro11 ;;
  all)     build_dasmxx; build_macro11 ;;
esac
