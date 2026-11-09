#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# gowin.sh -- the shared Gowin build/program library for the retrosim FPGA
# repos. SOURCED (not executed) by each repo's fpga/build.sh:
#
#   lib="../../retrosim-build/gowin.sh"
#   [ -f "$lib" ] || { echo "missing ../retrosim-build sibling (check it out beside this repository)"; exit 1; }
#   . "$lib"
#
#   gowin_board <board>            # resolve the board table (see below)
#   gowin_synth <base> <sdc> [...] # gw_sh build.tcl + retry + timing sign-off
#   gowin_prog <base>              # volatile SRAM load (--run 24 + --run 2)
#   gowin_prog_flash <base>        # persistent flash program+verify (board-specific)
#
# gowin_board sets: GOWIN_BOARD (canonical name), GOWIN_DEVICE, GOWIN_PART,
# GOWIN_PROGDEV (programmer_cli device/cable args + any $PROGDEV extras),
# GOWIN_FLASH_RUN (the bitstream flash-persist --run code).
#
# gowin_synth runs `$GWSH build.tcl` in the CALLER'S cwd (build.tcl reads the
# repo's exported env vars), makes up to three attempts past gw_sh launch
# flakiness (empty-log death; see ts804fpga/doc/gowin-timing-closure.md
# section 6 -- also NEVER run two gw_sh or a gw_sh + programmer_cli
# concurrently), renames impl/ -> impl_<base>/, and gates on the shared
# timing sign-off (tools/timing_signoff.py). Extra args after <sdc> pass
# through to the sign-off (e.g. --ship 66.667 --ship-clock clk_core).
#
# Environment: GWSH (gw_sh path, default `gw_sh`), PROGRAMMER_CLI
# (programmer_cli override; otherwise PATH, then a standard commercial
# /c/Gowin install), PROGDEV (REPLACES the board table's cable/location args
# when a host's cabling differs; the --device always comes from the table).
# QT_PLUGIN_PATH is cleared for the gw_sh invocation only (gw_sh wants its
# own Qt; run without oss-cad on PATH).

GOWIN_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- Workspace toolchain pin (toolchain.ninja beside this library) ----------
# THE one file a toolchain version bump edits. Resolution order everywhere:
# explicit env var, then the pin, then PATH / install discovery -- so a repo
# never needs to name a versioned install dir again.
_gowin_pin() {  # <name> -> pinned value (empty if absent)
  sed -n "s/^$1 *= *//p" "$GOWIN_LIB_DIR/toolchain.ninja" 2>/dev/null | head -1
}
# A set-but-DEAD absolute path (a long-running shell that predates a
# toolchain reinstall) falls through to the pin with a warning -- the exact
# stale-environment trap that otherwise resolves a deleted install.
case "${GWSH:-}" in
  */*| *\\*)
    if [ ! -f "$GWSH" ] && [ ! -f "$(echo "$GWSH" | tr '\\' '/')" ]; then
      echo "gowin.sh: ignoring stale GWSH ($GWSH does not exist); using the toolchain pin" >&2
      GWSH=""
    fi ;;
esac
if [ -z "${GWSH:-}" ]; then
  _gw_root="$(_gowin_pin gowin_root)"
  [ -n "$_gw_root" ] && [ -f "$_gw_root/IDE/bin/gw_sh.exe" ] && GWSH="$_gw_root/IDE/bin/gw_sh.exe"
  unset _gw_root
fi
GWSH="${GWSH:-gw_sh}"
# Normalize backslashes: a Windows-style path is valid to stat but Git Bash
# cannot exec it (the documented PROGRAMMER_CLI/GWSH trap).
GWSH="${GWSH//\\//}"

# Resolve the programmer independently of gw_sh.  Build hosts commonly keep
# Gowin off PATH (to avoid its bundled Qt/Python leaking into simulation), but
# silicon runners still need programmer_cli from a fresh non-interactive shell.
# Prefer an explicit override, then the toolchain pin, then PATH, then the
# newest standard commercial install.  Deliberately exclude Education
# installs: those are not accepted for signed-off builds and should not become
# an accidental board-programming dependency either.
_gw_pin_prog=""
_gw_root="$(_gowin_pin gowin_root)"
[ -n "$_gw_root" ] && [ -f "$_gw_root/Programmer/bin/programmer_cli.exe" ] && \
  _gw_pin_prog="$_gw_root/Programmer/bin/programmer_cli.exe"
unset _gw_root
case "${PROGRAMMER_CLI:-}" in
  */* | *\\*)
    if [ ! -f "$PROGRAMMER_CLI" ] && [ ! -f "$(echo "$PROGRAMMER_CLI" | tr '\\' '/')" ]; then
      echo "gowin.sh: ignoring stale PROGRAMMER_CLI ($PROGRAMMER_CLI does not exist); using the toolchain pin" >&2
      PROGRAMMER_CLI=""
    fi ;;
esac
if [ -n "${PROGRAMMER_CLI:-}" ]; then
  # Same backslash normalization as GWSH above.
  PROG="${PROGRAMMER_CLI//\\//}"
elif [ -n "$_gw_pin_prog" ]; then
  PROG="$_gw_pin_prog"
elif command -v programmer_cli >/dev/null 2>&1; then
  PROG="programmer_cli"
else
  PROG=""
  for _p in $(ls -d /c/Gowin/Gowin_V*_x64/Programmer/bin/programmer_cli.exe 2>/dev/null \
                  | grep -v Education | /usr/bin/sort -r); do
    PROG="$_p"; break
  done
  unset _p
  PROG="${PROG:-programmer_cli}"
fi
unset _gw_pin_prog

# ---- "is Gowin on this machine at all?" (vivado.sh's pattern) --------------
#   gowin_available   quiet predicate; 0 = usable, 1 = absent
#   gowin_require     one actionable message + return 127 (the shell's own
#                     "command not found" code, so a caller or CI can tell
#                     "tool absent, skip" apart from "build failed, fix it")
gowin_available() {
  case "$GWSH" in
    */*) [ -x "$GWSH" ] || [ -f "$GWSH" ] ;;
    *)   command -v "$GWSH" >/dev/null 2>&1 ;;
  esac
}

gowin_require() {
  gowin_available && return 0
  cat >&2 <<EOF
⛔ gw_sh not found — this step needs the Gowin toolchain and will be skipped.
   Looked for: \$GWSH ('$GWSH'), the workspace pin
   (retrosim-build/toolchain.ninja: gowin_root), then 'gw_sh' on PATH.
   Fix the pin (the ONE place a version bump edits) or point GWSH= at your
   install.

   ⓘ This is NOT a build failure and nothing is wrong with the design.
   The lint and simulation gates and the commit hooks run WITHOUT Gowin;
   only bitstream synthesis and board programming need it.
EOF
  return 127
}

# The one board table (canonical name first, legacy per-repo aliases after).
#
# Flash-persist codes come from the VENDOR's own table, not from folklore:
# SUG502 "Gowin Programmer User Guide", in the Programmer install under
# doc/EN. The section headings are what matter, because they are keyed to the
# device FAMILY and the codes do not carry across:
#
#   4.8  Embedded Flash of the LittleBee family   5, 6, 7   (GW1N parts)
#   4.9.1 External Flash of LittleBee, GW2A(R)    8, 9, 10, 11, 36, 37
#   4.9.2 Sipped Flash, GW2ANR-18C group          8, 9, 10, 11, 36, 37
#   4.9.3 External Flash of Arora V               52, 53, 54, 66, 68, 69
#
# So GW5A parts persist with 54 and GW2A(R) parts with **9**
# (exFlash Erase,Program,Verify) -- 8 is the same without the verify.
#
# ⚠ 4.9.1 and 4.9.2 landing on the same numbers is load-bearing here: JTAG ID
# 0x0000081B is shared by GW2A-18C, GW2AR-18C and GW2ANR-18C, and
# `programmer_cli --scan` says so in as many words ("One of them"). It cannot
# tell you which part you have -- but it does not need to, because all three
# take the same operation.
#
# ⛔ The Nano 20K row below says 5, which is the LittleBee EMBEDDED-flash op
# for a part in none of those families. Left as found rather than corrected
# blind: no Nano 20K was in front of the person who read the table, and a
# board table is not the place to guess twice. Verify it with the read-only
# `--run 11` (exFlash Verify) before trusting it -- on a GW2A(R) that prints
# `SPI flash detected: 0x......` and then passes or fails on the DATA, which
# is how you tell a supported operation from an inapplicable one.
#
# Data regions (ROM images at an offset) are separate: --run 54/36 with
# --spiaddr, per each repo's docs.
gowin_board() {
  local cabling
  # Reset per-board options so multiple calls in one shell cannot leak them.
  GOWIN_FLASH_CHECK=""
  case "$1" in
    nano20k | tang20k | tang_nano20k | tang_nano_20k)
      GOWIN_BOARD="nano20k"
      GOWIN_DEVICE="GW2AR-18C"; GOWIN_PART="GW2AR-LV18QN88C8/I7"
      # External SPI flash (a Winbond W25Q64, ID 0xEF4017), SUG502 4.9.1's
      # GW2A(R) ops: 8 = exFlash Erase,Program. 5 is EMBEDDED flash, which a
      # GW2AR-18C does not have ("Erase Failed!" at 0%). `--run 11` verifies
      # it separately; the part then boots it.
      cabling=""; GOWIN_FLASH_RUN=8 ;;
    # USB locations are host/session-dependent. Verify the device with
    # programmer_cli --scan --location <N> and override defaults via PROGDEV.
    # Device IDs: 60K 0x0001481B; 138K 0x0001081B.
    console60k | tang60k | tang_mega60k | tang_console60k)
      GOWIN_BOARD="console60k"
      GOWIN_DEVICE="GW5AT-60B"; GOWIN_PART="GW5AT-LV60PG484AC1/I0"
      cabling="--location 289"; GOWIN_FLASH_RUN=54 ;;     # GW5AT-60B 0x0001481B (verify w/ --scan)
    console138k | tang138k | tang_mega138k)
      GOWIN_BOARD="console138k"
      GOWIN_DEVICE="GW5AST-138C"; GOWIN_PART="GW5AST-LV138PG484AC1/I0"
      cabling="--location 6689"; GOWIN_FLASH_RUN=54 ;;    # GW5AST-138 0x0001081B (verify w/ --scan)
    mega138kpro | tang_mega138k_pro)
      GOWIN_BOARD="mega138kpro"
      GOWIN_DEVICE="GW5AST-138B"; GOWIN_PART="GW5AST-LV138FPG676AC1/I0"
      cabling=""; GOWIN_FLASH_RUN=54 ;;
    # Sipeed Tang Primer 25K core board (+ the 60033 Dock). The part number is
    # the ES bin Sipeed ships and is what every vendor board project targets;
    # GW5A-LV25MG121NC1/I0 is the same MBGA121N package in the SAME speed bin
    # (1) and gives an identical timing model if a board carries that marking.
    primer25k | tang_primer25k | tang_primer_25k | primer_25k)
      GOWIN_BOARD="primer25k"
      GOWIN_DEVICE="GW5A-25A"; GOWIN_PART="GW5A-LV25MG121NES"
      cabling=""; GOWIN_FLASH_RUN=54 ;;
    # Sipeed Tang Primer 20K core board (+ the Dock). GW2A-18C: an Arora
    # part with an EXTERNAL SPI flash on the core board, so it persists with
    # external-SPI operation (8), rather than embedded-flash operation 5.
    #
    # ⚠⚠ 8 (Erase,Program) and NOT 9 (Erase,Program,Verify), because on this
    # board's flash -- `SPI flash detected: 0x0B4017`, an XTX/Boya part rather
    # than the Winbond the tool is usually pointed at -- the VERIFY STAGE IS A
    # FALSE NEGATIVE. Measured: 9 reports `SPI Verify failed!` every time and
    # leaves a Timeout Error in the status register (bit 3; UG290 Table 7-13),
    # the standalone verify 11 fails the same way at 2.5/2/1 MHz, and the
    # board then BOOTS THAT FLASH PERFECTLY. 8 writes the same bytes, exits 0,
    # and GOWIN_FLASH_CHECK below verifies what actually matters.
    primer20k | tang_primer20k | tang_primer_20k | primer_20k)
      GOWIN_BOARD="primer20k"
      GOWIN_DEVICE="GW2A-18C"; GOWIN_PART="GW2A-LV18PG256C8/I7"
      cabling="--location 593"                            # host/session dependent: --scan-cables F
      GOWIN_FLASH_RUN=8; GOWIN_FLASH_CHECK=reprogram ;;   # SUG502 4.9.1
    *) echo "gowin.sh: unknown board '$1' (nano20k|primer20k|console60k|console138k|mega138kpro|primer25k)" >&2
       return 2 ;;
  esac
  # $PROGDEV (when set) REPLACES the table's cabling (a board's USB location /
  # cable index varies per host); the --device always comes from the table.
  GOWIN_PROGDEV="--device $GOWIN_DEVICE ${PROGDEV:-$cabling}"
}

# SDC coverage gate: does every `get_regs` pattern still name real RTL?
# Runs in ~1 s, BEFORE the 40-minute place-and-route, because the failure it
# catches is invisible afterwards -- a renamed or split module leaves a `-to`
# glob pointing at nothing, the constraint still reports `Actived`, and that
# half of the register plane is timed at N=1 forever. Worth 14 MHz once
# (the RL11+UBE planes) and -2.6 ns again (the RS2 ub_rh11 split).
# Set GOWIN_RTL_DIRS to the directories holding instantiating RTL -- the SoC
# TOP and every sibling repo's rtl/, not just the local one. Unset = skipped.
gowin_sdc_coverage() {  # <sdc>
  [ -n "${GOWIN_RTL_DIRS:-}" ] || return 0
  [ -f "$GOWIN_LIB_DIR/tools/sdc_coverage.py" ] || return 0
  local extra=""
  [ "${GOWIN_SDC_COVERAGE_GATE:-1}" = 1 ] || extra="--warn-only"
  python "$GOWIN_LIB_DIR/tools/sdc_coverage.py" $extra "$1" $GOWIN_RTL_DIRS
}

# --- Host-global build lock --------------------------------------------------
# The gw_sh license is single-instance PER HOST, so the lock is host-global
# (not per-repo): $GOWIN_LOCK_DIR, default under the system temp dir. Ported
# from hh-v1170's keyed build lock (owner file with pid/host/time/command so a
# collision names its owner instead of impersonating a build failure).
# ⚠ Deliberately NO `trap EXIT` here: several repos layer their own locks with
# EXIT traps around gowin_synth, and bash keeps only one EXIT trap -- so
# gowin_synth releases explicitly on every path instead. A lock leaked by a
# kill -9 is detected as stale via its recorded pid and reclaimed.
GOWIN_LOCK_DIR="${GOWIN_LOCK_DIR:-${TMPDIR:-/tmp}/gowin-host-build.lock}"

gowin_lock_release() {
  rm -f "$GOWIN_LOCK_DIR/owner" 2>/dev/null || true
  rmdir "$GOWIN_LOCK_DIR" 2>/dev/null || true
}

gowin_lock_acquire() {  # <what> -- returns 73 if another build holds the host
  local what="$1" owner_pid=""
  if ! mkdir "$GOWIN_LOCK_DIR" 2>/dev/null; then
    owner_pid="$(sed -n 's/^pid=//p' "$GOWIN_LOCK_DIR/owner" 2>/dev/null | head -1)"
    if [ -n "$owner_pid" ] && ! kill -0 "$owner_pid" 2>/dev/null; then
      echo "[lock] reclaiming stale gowin lock (owner pid $owner_pid is gone)" >&2
      gowin_lock_release
      mkdir "$GOWIN_LOCK_DIR" 2>/dev/null || return 73
    else
      echo "[$what] REFUSING TO BUILD: another Gowin build holds the host lock." >&2
      sed 's/^/    /' "$GOWIN_LOCK_DIR/owner" 2>/dev/null >&2
      echo "  WAIT for it (single-instance license; never kill the other run)." >&2
      echo "  If no such process exists, remove only $GOWIN_LOCK_DIR" >&2
      return 73
    fi
  fi
  {
    printf 'what=%s\n' "$what"
    printf 'pid=%s\n' "$$"
    printf 'host=%s\n' "$(hostname 2>/dev/null || echo unknown)"
    printf 'started_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'command=%s\n' "$0"
  } > "$GOWIN_LOCK_DIR/owner"
  return 0
}

gowin_synth() {  # <base> <sdc> [timing_signoff extra args...]
  gowin_require || return $?
  gowin_lock_acquire "${1:-gowin_synth}" || return 73
  local _rc=0
  _gowin_synth_locked "$@" || _rc=$?
  gowin_lock_release
  return $_rc
}

# Promote impl/ to impl_<base>/. Windows may refuse a rename while a process
# holds a handle inside the directory; retry, then copy. Stop if promotion
# fails so sign-off cannot inspect a missing or stale report.
_gowin_promote_impl() {  # <base>
  local base="$1" try
  for try in 1 2 3; do
    mv impl "impl_${base}" 2>/dev/null && return 0
    sleep 2
  done
  echo "[$base] ⚠ could not RENAME impl/ (a process holds a handle inside it --" >&2
  echo "[$base]   a shell cwd, an editor, the indexer); copying it instead" >&2
  rm -rf "impl_${base}" 2>/dev/null || true
  if ! cp -r impl "impl_${base}"; then
    echo "[$base] *** could not copy impl/ to impl_${base}/ either -- the reports" >&2
    echo "[$base] ***   are still in impl/. Nothing below would be judging THIS build." >&2
    return 1
  fi
  if ! rm -rf impl 2>/dev/null; then
    echo "[$base] ⚠ impl/ could not be removed after the copy. The NEXT build must" >&2
    echo "[$base]   not start until it is gone, or it will nest into a stale tree." >&2
  fi
  return 0
}

_gowin_synth_locked() {
  # GOWIN_TCL (default build.tcl) selects the flow script -- repos hosting
  # more than one machine top set it per target (hh-c128's build_c64.tcl).
  local base="$1" sdc="$2"; shift 2
  local tcl="${GOWIN_TCL:-build.tcl}"
  # A gw_sh that is ALREADY running takes the license and kills the one you are
  # about to launch (silently, empty log) -- catches gw_sh instances the lock
  # cannot see (the IDE, a manual run). Refuse rather than burn the retries:
  # a wedged sweep looks exactly like a swept result otherwise.
  if command -v tasklist > /dev/null 2>&1; then
    if tasklist //FI "IMAGENAME eq gw_sh.exe" 2>/dev/null | grep -q gw_sh; then
      echo "[$base] REFUSING TO BUILD: a gw_sh is already running (license conflict)." >&2
      echo "  Serialize Gowin runs -- never overlap a synth with a synth or a flash/scan." >&2
      return 1
    fi
  fi
  gowin_sdc_coverage "$sdc" || {
    echo "[$base] *** SDC COVERAGE FAILED -- not starting a 40 minute PnR ***" >&2
    return 1
  }
  local attempt
  for attempt in 1 2 3; do
    [ -d impl ] && mv impl ".impl_old_$$" 2>/dev/null
    rm -rf ".impl_old_$$" 2>/dev/null || true
    [ -d impl ] && rm -rf impl 2>/dev/null
    # A leftover impl/ that can be neither moved nor removed would have gw_sh
    # write THIS build over the top of an old one (see _gowin_promote_impl).
    if [ -d impl ]; then
      echo "[$base] REFUSING TO BUILD: a stale impl/ is held open and cannot be removed." >&2
      echo "  Close whatever has a file or its cwd inside it and rerun." >&2
      return 1
    fi
    # Preserve one generation of reports for build-to-build comparison.
    rm -rf "impl_${base}.prev" 2>/dev/null || true
    [ -d "impl_${base}" ] && mv "impl_${base}" "impl_${base}.prev" 2>/dev/null
    # Refuse a failed rotation: moving impl/ into an existing destination
    # would nest the new tree and leave sign-off reading a stale report.
    if [ -d "impl_${base}" ]; then
      echo "[$base] REFUSING TO BUILD: impl_${base} could not be rotated to .prev" >&2
      echo "  (a file inside it is held open -- an editor, a viewer, a tail)." >&2
      echo "  Close it and rerun; building now would NEST the new build inside" >&2
      echo "  the old one and the sign-off would judge the STALE report." >&2
      return 1
    fi
    # Back off after a vendor launch failure. Empty logs can persist across
    # all retries immediately after another run; report that failure clearly.
    sleep $((attempt * 5))
    # Preserve stdout: a pre-synthesis Tcl error can leave no synthesis log.
    _gwout="${TMPDIR:-/tmp}/gwsh_${base}.out"
    QT_PLUGIN_PATH="" "$GWSH" "$tcl" > "$_gwout" 2>&1 || true
    [ -f "impl/pnr/${base}.fs" ] && break
    # A synthesis-only diagnostic run (the caller's tcl chose `run syn`) writes
    # a netlist and no bitstream -- that is a SUCCESS, not a failure.
    { [ -f "impl/gwsynthesis/${base}.vg" ] && [ ! -d impl/pnr ]; } && break
    # SAY SO. A silent retry is how a launch failure gets mistaken for a build
    # failure (and a build failure for a timing result).
    if [ ! -s "impl/gwsynthesis/${base}.log" ]; then
      echo "[$base] attempt $attempt: gw_sh produced NO LOG (launch failure OR a pre-synthesis Tcl error) -- retrying" >&2
      if [ -s "$_gwout" ]; then
        echo "[$base]   gw_sh said:" >&2
        tail -5 "$_gwout" | sed 's/^/    /' >&2
      fi
    else
      echo "[$base] attempt $attempt: gw_sh ran but produced no bitstream" >&2
      # Synthesis errors are deterministic; retrying cannot repair them.
      _syn="$(tr -d '\r' < "impl/gwsynthesis/${base}.log" 2>/dev/null | grep -m 3 -E '^ERROR' || true)"
      if [ -n "$_syn" ]; then
        echo "[$base] *** SYNTHESIS ERROR -- not retrying (deterministic) ***" >&2
        echo "$_syn" | sed 's/^/    /' >&2
        if echo "$_syn" | grep -q 'RP0001'; then
          echo "[$base]   RP0001 on a DFF count far above the part usually means the" >&2
          echo "[$base]   design asked for MORE BLOCK RAM than the device has: synthesis" >&2
          echo "[$base]   builds the overflow out of flip-flops and then trips the DFF" >&2
          echo "[$base]   limit. Count the BSRAM, not the registers." >&2
        fi
        break
      fi
      # A TA-class error identifies an invalid SDC object or pattern.
      # Fail immediately rather than rerunning placement with the same SDC.
      _ta="$(tr -d '\r' < "impl/pnr/${base}.log" 2>/dev/null | grep -m 3 -E '^ERROR +\(TA[0-9]+\)' || true)"
      if [ -n "$_ta" ]; then
        echo "[$base] *** SDC CONSTRAINT ERROR -- not retrying (deterministic) ***" >&2
        echo "$_ta" | sed 's/^/    /' >&2
        echo "[$base]   An SDC pattern names an object this netlist does not have." >&2
        echo "[$base]   A zero-match get_regs OR get_pins glob is fatal, by design --" >&2
        echo "[$base]   fix or delete the pattern; re-rolling the placer cannot help." >&2
        break
      fi
      # A completed router that reports PR0004 is another real result, not
      # the empty-log launch flake this loop exists to mask. Gowin's placer is
      # deterministic for a fixed option set, so three identical 40-minute
      # runs cannot improve it; preserve this attempt and let the caller move
      # to the documented placer/retiming sweep instead.
      _pr="$(tr -d '\r' < "impl/pnr/${base}.log" 2>/dev/null | grep -m 3 -E '^ERROR +\(PR0004\)' || true)"
      if [ -n "$_pr" ]; then
        echo "[$base] *** ROUTING FAILED -- not retrying identical options ***" >&2
        echo "$_pr" | sed 's/^/    /' >&2
        break
      fi
    fi
  done
  if [ ! -f "impl/pnr/${base}.fs" ] && [ ! -f "impl/gwsynthesis/${base}.vg" ]; then
    if [ ! -s "impl/gwsynthesis/${base}.log" ]; then
      # No log at all is NOT a synthesis error -- do not print an empty
      # "synthesis errors:" heading and let the caller infer an RTL problem.
      echo "[$base] build FAILED: gw_sh never produced a log after 3 attempts." >&2
      if [ -s "$_gwout" ]; then
        echo "  gw_sh's own output (${_gwout}):" >&2
        tail -10 "$_gwout" | sed 's/^/    /' >&2
        echo "  A Tcl error above (missing file, bad env var) is the ROOT CAUSE;" >&2
        echo "  only with NO output at all is this the launch flake. Other causes:" >&2
      else
        echo "  This is a LAUNCH failure, not an RTL failure. Known causes:" >&2
      fi
      echo "    * another gw_sh / programmer_cli running (serialize Gowin tools)" >&2
      echo "    * heavy host load (a parallel sim or cargo build) -- give it the machine" >&2
      echo "    * GWSH unset or wrong, or PYTHONIOENCODING set (unset it)" >&2
      return 1
    fi
    echo "[$base] build FAILED (no bitstream). Synthesis errors:" >&2
    tr -d '\r' < "impl/gwsynthesis/${base}.log" 2> /dev/null \
      | grep -iE 'error|cannot' | head -10 || true
    return 1
  fi
  if [ ! -f "impl/pnr/${base}.fs" ]; then
    # A synthesis-only run leaves no pnr/ directory. If PnR was attempted,
    # a missing bitstream is a failure even when synthesis succeeded.
    if [ -d impl/pnr ]; then
      _gowin_promote_impl "$base" || return 1
      echo "[$base] *** PnR FAILED -- no bitstream. This is NOT a pass. ***" >&2
      tr -d '\r' < "impl_${base}/pnr/${base}.log" 2>/dev/null \
        | grep -iE '^ERROR|unrouted|cannot' | head -5 >&2 || true
      # ⚠ Only reachable when the log carries NO TA-class error (the retry
      # loop breaks out and reports those itself), so this advice is now
      # given only for a genuine router/placer failure.
      echo "[$base] ⭐ PR0004/unrouted is a PLACER pathology on an unmeasured" >&2
      echo "    netlist, not an RTL error: flip this repo's placer knob" >&2
      echo "    (e.g. V1170PRO_PLACE / J11_SOC_PLACE, 1<->2) and retry." >&2
      return 1
    fi
    _gowin_promote_impl "$base" || return 1
    echo "[$base] SYNTHESIS-ONLY run -- netlist in impl_${base}/gwsynthesis/, no bitstream, no timing."
    gowin_report_ram "$base"
    gowin_gate_comb_loops "$base" || return 1
    gowin_report_warnings "$base" || return 1
    return 0
  fi
  _gowin_promote_impl "$base" || return 1
  echo "[$base] bitstream: impl_${base}/pnr/${base}.fs"
  gowin_report_usage "$base"
  gowin_report_ram "$base"
  gowin_gate_comb_loops "$base" || return 1
  gowin_report_warnings "$base" || return 1
  if python "$GOWIN_LIB_DIR/tools/timing_signoff.py" \
       "impl_${base}/pnr/${base}_tr_content.html" "$sdc" "$@"; then
    echo "[$base] TIMING MET (sign-off: TNS + margins + SDC health)"
  else
    echo "[$base] *** TIMING SIGN-OFF FAILED (see above) ***"; return 1
  fi
}

# Print the PnR Resource Usage Summary as a one-line record beside the Fmax.
# WHY: a timing regression's shape is in the LOGIC:REGISTER ratio (a refactor
# that adds combinational depth and no state is ~pure Fmax loss), and without a
# per-build utilization record, attributing one costs a full controlled rebuild
# from git worktrees. Cheap to log, expensive to reconstruct -- see
# ../ts804fpga/doc/gowin-timing-closure.md section 6.
gowin_report_usage() {  # <base>
  local base="$1" rpt="impl_$1/pnr/$1.rpt.txt"
  [ -f "$rpt" ] || return 0
  tr -d '\r' < "$rpt" | awk -v b="$base" '
    /Resource Usage Summary/ {inb=1}
    inb && /^  Logic  / {split($0,f,"|"); gsub(/ /,"",f[2]); gsub(/ /,"",f[3]); lg=f[2]" ("f[3]")"}
    inb && /--LUT,ALU,ROM16/ {sub(/.*\|/,"",$0); lut=$0}
    inb && /^  Register  / {split($0,f,"|"); gsub(/ /,"",f[2]); reg=f[2]}
    inb && /^  CLS  / {split($0,f,"|"); gsub(/ /,"",f[2]); gsub(/ /,"",f[3]); cls=f[2]" ("f[3]")"}
    inb && /^  BSRAM  / {split($0,f,"|"); gsub(/ /,"",f[2]); bs=f[2]}
    inb && /^  DSP  / {split($0,f,"|"); gsub(/ /,"",f[2]); ds=f[2]; inb=0}
    END {printf "  usage: Logic %s  Register %s  CLS %s  BSRAM %s  DSP %s\n", lg, reg, cls, bs, ds}'
}

# The inferred-RAM census, grouped by the source array that produced it.
# WHY: `get_regs` binds registers and this SDC dialect has no `get_pins`, so an
# array that lowers to RAM16/BSRAM/RAMREG is unreachable by EVERY timing
# exception -- silently, while the constraint still reports Actived. Any name
# here that also shows up as a `-to` endpoint in <base>.timing_paths is
# un-constrainable by construction and must be fixed in RTL, not in the SDC
# (gowin-timing-closure.md sections 2.8 and 3.1). Cheap enough to print every
# build so the day an array starts inferring is the day you find out.
gowin_report_ram() {  # <base>
  local vg="impl_$1/gwsynthesis/$1.vg"
  [ -f "$vg" ] || vg="impl/gwsynthesis/$1.vg"
  [ -f "$vg" ] || return 0
  local census
  census="$(tr -d '\r' < "$vg" | grep -E '(RAM16|RAMREG|SDPB|DPB|SP|pROM)[A-Z0-9]* ' \
    | sed -E 's/^[[:space:]]*//; s/ \(.*$//' \
    | awk 'NF>=2 {n=$2; sub(/_[0-9]+_s[0-9]*$/,"",n); print $1, n}' \
    | sort | uniq -c | sort -rn | head -12)"
  [ -n "$census" ] || return 0
  echo "  inferred RAM census (cell / source array):"
  echo "$census" | sed 's/^/    /'
}

# Synthesis-warning surface. Default: REPORT (never silently green).
# GOWIN_WARN_GATE=1 makes warnings fatal. Review warnings independently of
# timing closure: unsupported set/reset combinations can pass timing while
# producing incorrect hardware behavior.
# ⚠⚠ COMBINATIONAL LOOPS -- ALWAYS FATAL, no opt-out, separate from the
# blanket warning gate above. A netlist that is not a DAG is INDETERMINATE on
# real silicon: the loop free-runs, and nothing downstream is trustworthy --
# not the timing numbers (STA cannot analyse a cycle), not the functional
# result, not a bitstream that appears to work.
#
# Check loops independently of the optional blanket warning gate, so benign
# synthesis warnings do not prevent rejection of an indeterminate netlist.
#
# ⚠ VERILATOR CANNOT COVER FOR YOU: it reports a cycle as UNOPTFLAT and then
# iterates it to a fixed point, so the benches stay green. Synthesis is the
# FIRST tool in the chain that refuses. Treat a UNOPTFLAT on a design signal
# as an error too (hh-unibus WORKFLOW).
gowin_gate_comb_loops() {  # <base>
  local base="$1" log="impl_$1/gwsynthesis/$1.log"
  [ -f "$log" ] || return 0
  local loops; loops="$(tr -d '\r' < "$log" | grep -E 'AG0100|AG0101|not one directed acyclic graph' || true)"
  [ -n "$loops" ] || return 0
  echo "[$base] *** COMBINATIONAL LOOP IN THE NETLIST -- REFUSING THIS BUILD ***" >&2
  echo "$loops" | head -12 | sed 's/^/    /' >&2
  echo "  A netlist that is not a DAG is INDETERMINATE in silicon. Timing" >&2
  echo "  numbers from this build are meaningless and a bitstream from it" >&2
  echo "  cannot be trusted, however well it appears to run." >&2
  echo "  FIX THE RTL: find the signal in the cycle and break the feedback." >&2
  echo "  Verilator may continue after reporting" >&2
  echo "  UNOPTFLAT and iterates to a fixed point." >&2
  return 1
}

gowin_report_warnings() {  # <base>
  local base="$1" log="impl_$1/gwsynthesis/$1.log" n
  [ -f "$log" ] || return 0
  local warns; warns="$(tr -d '\r' < "$log" | grep -E '^WARN' | sort | uniq -c | sort -rn)"
  [ -n "$warns" ] || return 0
  n="$(echo "$warns" | wc -l | tr -d ' ')"
  echo "  synthesis warnings: $n distinct"
  echo "$warns" | head -8 | sed 's/^/    /'
  if [ "${GOWIN_WARN_GATE:-0}" = 1 ]; then
    echo "[$base] *** SYNTHESIS WARNINGS ARE FATAL (GOWIN_WARN_GATE=1) ***" >&2
    return 1
  fi
  return 0
}

gowin_fs_abs() {  # <base> -> absolute forward-slash bitstream path
  cygpath -m "$PWD/impl_$1/pnr/$1.fs" 2>/dev/null || echo "$PWD/impl_$1/pnr/$1.fs"
}

# The bitstream freshness gate lives in fpga_common.sh, shared with
# vivado.sh. gowin_fs_freshness is the vendor-named entry point.
. "$GOWIN_LIB_DIR/fpga_common.sh"
gowin_fs_freshness() { retrosim_fs_freshness "$@"; }

gowin_prog() {  # <base> -- volatile SRAM erase + load
  local base="$1"
  [ -f "impl_${base}/pnr/${base}.fs" ] || { echo "[$base] no bitstream -- run synth first" >&2; return 1; }
  gowin_fs_freshness "impl_${base}/pnr/${base}.fs" || return 3
  _gowin_program_artifact "$(gowin_fs_abs "$base")" sram $GOWIN_PROGDEV
}

gowin_prog_flash() {  # <base> -- persistent bitstream flash (program + verify)
  local base="$1"
  [ -f "impl_${base}/pnr/${base}.fs" ] || { echo "[$base] no bitstream -- run synth first" >&2; return 1; }
  gowin_fs_freshness "impl_${base}/pnr/${base}.fs" || return 3
  _gowin_program_artifact "$(gowin_fs_abs "$base")" flash $GOWIN_PROGDEV
}

# The caller has validated freshness/timing. Unlike the legacy GOWIN_PROGDEV
# string, this internal primitive preserves every programmer argument boundary.
_gowin_program_artifact() {  # <absolute artifact> <sram|flash> [programmer args...]
  local artifact="$1" mode="$2"
  shift 2
  [ -f "$artifact" ] || { echo "program: no artifact $artifact" >&2; return 1; }
  case "$mode" in
    sram) "$PROG" --run 24 "$@" && "$PROG" --run 2 "$@" --fsFile "$artifact"; return $? ;;
    flash) ;;
    *) echo "program: mode must be sram or flash" >&2; return 2 ;;
  esac
  # ⚠ Start from a CLEAN status register.  UG290 "Clearing Status Code Errors"
  # says so in as many words -- make sure there are none before programming
  # Flash -- and this is not paperwork: a Primer 20K flash that began with a
  # Timeout Error (status bit 3) programmed, verified nothing, and left the
  # part unable to boot what had just been written.  A Reprogram clears it and
  # the identical command then works.  Costs 0.14 s, and only where the board
  # asked for the check, so no other board's flow changes.
  if [ "${GOWIN_FLASH_CHECK:-}" = reprogram ]; then
    "$PROG" --run 1 "$@" >/dev/null 2>&1 || return 1
  fi
  "$PROG" --run "$GOWIN_FLASH_RUN" "$@" --fsFile "$artifact" || return 1
  [ "${GOWIN_FLASH_CHECK:-}" = reprogram ] || return 0
  gowin_flash_check "$@"
}

# Did the part actually come up on what is now in its flash?  Reprogram (the
# vendor's word for "reboot and reload from flash") and read the status back.
#
# This exists because a board can need it -- the Primer 20K's flash makes the
# tool's own SPI verify cry wolf -- and because it asks a strictly better
# question than a byte compare does: not "are those the bytes I sent" but "does
# this part BOOT them".
#
# ⚠ The wait is the whole trick. Reading the codes straight after Reprogram
# reports User Code 0x00000000 and a DONE of 0, which reads exactly like a
# failed flash and is nothing of the kind: a GW2A-18 pulls the better part of a
# megabyte over MSPI and simply is not finished yet. Two seconds is enough at
# 0x0DD800 bytes; five is what this waits.
#
# ⛔ Opt-in per board (GOWIN_FLASH_CHECK=reprogram) rather than default,
# because "--run 1 reloads from flash" is NOT true everywhere -- the Console
# 138K's flash flow is on record as leaving the part unconfigured -- and a
# check that fails on a board that flashed correctly is worse than no check.
gowin_flash_check() {
  local out
  local -a args=("$@")
  if [ "$#" -eq 0 ]; then read -r -a args <<< "$GOWIN_PROGDEV"; fi
  "$PROG" --run 1 "${args[@]}" >/dev/null 2>&1 || return 1
  sleep 5
  out="$("$PROG" --run 0 "${args[@]}" 2>&1)" || return 1
  echo "$out" | grep -E "Code is" | sed "s/^/  /"
  # UG290 Table 7-13: bit 13 DONE Final. 0x?6020 / 0x?2020 is a configured
  # GW2A; a status with DONE clear means it did not boot what was written.
  case "$out" in
    *"Status Code is: 0x"*[26]020*) echo "[flash] the part booted from flash"; return 0 ;;
  esac
  echo "[flash] the part did NOT boot what was just written" >&2
  return 4
}

gowin_prog_data() {  # <image> <spiaddr> -- external-flash DATA-region write
  # ROM containers / disk images at an offset (a2600box 0x500000, the v180
  # RomWBW ROMs at 0x70_0000/0x78_0000, tvi955's hh-usbh 6809 firmware at
  # 0x68_0000...). ⚠ These offsets are CONTESTED on the shared Console 138K --
  # they are per-project conventions, not a reservation, and a stale image left
  # at one of them impersonates a broken SoC. Measure your bitstream's true end
  # before choosing one (tvi955's is 4.56 MiB), and record it in the board
  # README. Immediately after
  # a config-region write (or with the user design driving the flash pads) the
  # FIRST data write can fail fast in ~2 s -- and programmer_cli exits 0
  # either way, so the transcript is grepped and the write retried (--run
  # reloads its own GAO bridge).
  local img="$1" addr="$2" out ok=0 attempt abs
  [ -f "$img" ] || { echo "gowin_prog_data: no such image: $img" >&2; return 1; }
  case "$img" in
    *.fs | *.bin) ;;
    *) echo "gowin_prog_data: programmer_cli rejects '$img' -- copy it to a .bin first" >&2; return 1 ;;
  esac
  abs="$(cygpath -m "$(cd "$(dirname "$img")" && pwd)/$(basename "$img")" 2>/dev/null || echo "$img")"
  for attempt in 1 2 3; do
    out="$("$PROG" --run "$GOWIN_FLASH_RUN" $GOWIN_PROGDEV --spiaddr "$addr" --fsFile "$abs" 2>&1)" || true
    if echo "$out" | grep -q "successfully"; then ok=1; break; fi
    echo "[prog-data] attempt $attempt failed (the GAO-bridge fast-fail) -- retrying" >&2
  done
  [ "$ok" = 1 ] || { echo "$out" | tail -5 >&2; echo "gowin_prog_data: FAILED" >&2; return 1; }
  echo "[prog-data] $(basename "$img") programmed+verified at $addr"
}

# One-line synthesis-health record + optional gates -- the block five repos'
# syn/run.sh carried as near-identical copies (hh-j11's converted form).
#   gowin_report_synth_health <base> [--fatal warns,swept,latches] [--impl dir]
# (--impl for flows that leave gw_sh's impl/ un-renamed; default impl_<base>.)
gowin_report_synth_health() {
  local base="$1" fatal="" impl="" synlog rpt trc
  shift
  while [ $# -gt 0 ]; do
    case "$1" in
      --fatal) fatal="${2:-}"; shift 2 ;;
      --impl) impl="${2:-}"; shift 2 ;;
      *) shift ;;
    esac
  done
  impl="${impl:-impl_${base}}"
  synlog="${impl}/gwsynthesis/${base}.log"
  rpt="${impl}/pnr/${base}.rpt.txt"
  trc="${impl}/pnr/${base}_tr_content.html"
  local warns swept latch logic regs bsram fmax fail=0
  warns=$(tr -d '\r' < "$synlog" 2>/dev/null | grep -icE "WARN|warning" || true); warns=${warns:-0}
  swept=$(tr -d '\r' < "$synlog" 2>/dev/null | grep -ic "swept in optimizing" || true); swept=${swept:-0}
  latch=$(grep -iE 'Register as Latch' "$rpt" 2>/dev/null | grep -oE '[0-9]+/' | head -1 | tr -d / || true)
  logic=$(grep -iE 'LUT,ALU,ROM16' "$rpt" 2>/dev/null | awk -F'|' '{print $2}' | sed -E 's/^ +//; s/ +$//' | head -1 || true)
  regs=$(grep -iE '^ *Register ' "$rpt" 2>/dev/null | grep -oE '[0-9]+/' | head -1 | tr -d / || true)
  bsram=$(grep -iE '^ *BSRAM ' "$rpt" 2>/dev/null | awk -F'|' '{print $2}' | sed -E 's/^ +//; s/ +$//' | head -1 || true)
  fmax=$(sed -E 's/<[^>]+>/ /g' "$trc" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\(MHz\)' | sed -n 2p || true)
  echo "[$base] warnings=$warns swept=$swept latches=${latch:-?} fmax=${fmax:-?} regs=${regs:-?} logic=${logic:-?} bsram=${bsram:-?}"
  case ",$fatal," in *,warns,*) [ "$warns" != 0 ] && { echo "[$base] *** synthesis warnings (see $synlog) ***" >&2; fail=1; } ;; esac
  case ",$fatal," in *,swept,*) [ "$swept" != 0 ] && { echo "[$base] *** modules swept in optimizing ***" >&2; fail=1; } ;; esac
  case ",$fatal," in *,latches,*) [ "${latch:-0}" != 0 ] && { echo "[$base] *** latches inferred ***" >&2; fail=1; } ;; esac
  return $fail
}
