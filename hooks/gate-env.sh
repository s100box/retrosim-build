# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# gate-env.sh -- shared pre-commit/pre-push gate environment. SOURCE this at
# the top of every repo's .githooks hook (right after `set -e`):
#
#   root="$(git rev-parse --show-toplevel)"
#   [ -f "$root/../retrosim-build/hooks/gate-env.sh" ] && . "$root/../retrosim-build/hooks/gate-env.sh"
#
# It provides, for every hook, uniformly:
#
# 1. The SKIP_GATE=1 bypass (exits the hook successfully for WIP commits).
# 2. Robust tool PATH setup for Verible and the OSS CAD Suite. CRITICAL
#    detail: the tool dirs are (re-)prepended even when the tools are already
#    findable on PATH. Under `git commit`, Git-for-Windows prepends its own
#    mingw64/usr dirs, whose same-named DLLs shadow oss-cad's -- iverilog then
#    dies instantly with its stderr typically discarded, so the hook fails
#    with no visible error while an interactive run passes. Prepending oss-cad's bin AND lib (lib is
#    needed on Windows -- bin alone exits 127 on missing DLLs) ahead of
#    git's dirs restores correct DLL resolution.
#
# Resolution order: explicit env ($OSS_CAD_SUITE / $VERIBLE_ROOT / $GWSH /
# $PROGRAMMER_CLI) wins, else the workspace toolchain pin
# (../toolchain.ninja -- THE single file a version bump edits), else a
# release unzipped under the user's home ($HOME can be redirected, e.g.
# Cadence sets C:\SPB_Data, so also try $USERPROFILE and /c/Users/<name>).
# Nothing found = leave PATH alone and let the repo's own gate scripts skip
# gracefully; this file never fails the hook by itself.

if [ "${SKIP_GATE:-}" = "1" ]; then
  echo "gate: SKIP_GATE=1 -- skipping (WIP commit)"
  exit 0
fi

# --- Workspace toolchain pin (../toolchain.ninja) ----------------------------
# `name = value` lines; values may contain spaces. Already-set env wins.
_ge_pin_file="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)/toolchain.ninja"
_ge_pin() {  # <name> -> value (empty if absent)
  [ -f "$_ge_pin_file" ] || return 0
  sed -n "s/^$1 *= *//p" "$_ge_pin_file" | head -1
}
# A stale shell must not shadow the workspace pin after a tool reinstall.
# Keep live explicit overrides; discard missing tool roots before discovery.
for _ge_var in VERIBLE_ROOT OSS_CAD_SUITE VS_ROOT GWSH PROGRAMMER_CLI; do
  _ge_value="${!_ge_var:-}"
  if [ -n "$_ge_value" ] && [ ! -e "$_ge_value" ]; then
    echo "gate-env.sh: ignoring stale $_ge_var ($_ge_value does not exist); using discovery" >&2
    unset "$_ge_var"
  fi
done
unset _ge_var _ge_value
if [ -z "${VERIBLE_ROOT:-}" ]; then
  _v="$(_ge_pin verible_root)"
  [ -n "$_v" ] && [ -d "$_v" ] && VERIBLE_ROOT="$_v"
fi
if [ -z "${OSS_CAD_SUITE:-}" ]; then
  _v="$(_ge_pin oss_cad_suite)"
  [ -n "$_v" ] && [ -d "$_v" ] && OSS_CAD_SUITE="$_v"
fi
_gr="$(_ge_pin gowin_root)"
if [ -n "$_gr" ] && [ -d "$_gr" ]; then
  [ -z "${GWSH:-}" ] && [ -f "$_gr/IDE/bin/gw_sh.exe" ] && export GWSH="$_gr/IDE/bin/gw_sh.exe"
  [ -z "${PROGRAMMER_CLI:-}" ] && [ -f "$_gr/Programmer/bin/programmer_cli.exe" ] && \
    export PROGRAMMER_CLI="$_gr/Programmer/bin/programmer_cli.exe"
fi
_vsr="$(_ge_pin vs_root)"
[ -z "${VS_ROOT:-}" ] && [ -n "$_vsr" ] && [ -d "$_vsr" ] && export VS_ROOT="$_vsr"
# The sdcc-6809 fork (native Windows build; layout bin/ include/ lib/<port>/).
if [ -z "${SDCC_M6809_ROOT:-}" ]; then
  _v="$(_ge_pin sdcc_m6809_root)"
  [ -n "$_v" ] && [ -d "$_v" ] && export SDCC_M6809_ROOT="$_v"
fi
unset -f _ge_pin 2>/dev/null || true
unset _ge_pin_file _gr _vsr _v 2>/dev/null || true

_ge_homes() {
  # candidate home dirs, POSIX-normalized
  for _h in "${HOME:-}" "${USERPROFILE:-}" "/c/Users/${USERNAME:-${USER:-}}"; do
    [ -n "$_h" ] || continue
    command -v cygpath >/dev/null 2>&1 && _h="$(cygpath -u "$_h" 2>/dev/null || echo "$_h")"
    echo "$_h"
  done
}

# --- OSS CAD Suite (iverilog/vvp/yosys) --------------------------------------
if [ -z "${OSS_CAD_SUITE:-}" ]; then
  for _h in $(_ge_homes); do
    if [ -x "$_h/oss-cad-suite/bin/iverilog" ] || [ -x "$_h/oss-cad-suite/bin/iverilog.exe" ]; then
      OSS_CAD_SUITE="$_h/oss-cad-suite"; break
    fi
  done
fi
if [ -n "${OSS_CAD_SUITE:-}" ]; then
  _ocs="$OSS_CAD_SUITE"
  command -v cygpath >/dev/null 2>&1 && _ocs="$(cygpath -u "$_ocs" 2>/dev/null || echo "$_ocs")"
  export OSS_CAD_SUITE
  PATH="$_ocs/bin:$_ocs/lib:$PATH"
fi

# --- Verible ------------------------------------------------------------------
if [ -z "${VERIBLE_ROOT:-}" ]; then
  for _h in $(_ge_homes); do
    for _d in "$_h"/verible/verible-*; do
      if [ -x "$_d/verible-verilog-lint" ] || [ -x "$_d/verible-verilog-lint.exe" ]; then
        VERIBLE_ROOT="$_d"; break 2
      fi
    done
  done
fi
if [ -n "${VERIBLE_ROOT:-}" ]; then
  _vr="$VERIBLE_ROOT"
  command -v cygpath >/dev/null 2>&1 && _vr="$(cygpath -u "$_vr" 2>/dev/null || echo "$_vr")"
  export VERIBLE_ROOT
  PATH="$_vr:$PATH"
fi

export PATH
unset -f _ge_homes 2>/dev/null || true
unset _h _d _ocs _vr 2>/dev/null || true

# Primary hooks consume the metadata checker through this bootstrap. Build
# wrappers sourcing the environment do not acquire an unrelated Git check.
case "$(basename "$0")" in
  pre-commit|pre-push)
    _ge_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
    _ge_shared="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    if [ -n "$_ge_root" ] && [ "$_ge_root" != "$_ge_shared" ]; then
      _ge_python="$(command -v python3 || command -v python || true)"
      [ -n "$_ge_python" ] || { echo "consumer audit: Python is required" >&2; exit 127; }
      "$_ge_python" "$_ge_shared/tools/audit_consumers.py" "$_ge_root" || exit $?
    fi
    unset _ge_root _ge_shared _ge_python
    ;;
esac
