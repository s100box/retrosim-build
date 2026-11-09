#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# Pre-commit SDC coverage gate -- source this from a repo's .githooks/pre-commit:
#
#   . ../retrosim-build/hooks/sdc-coverage-gate.sh && sdc_coverage_gate || exit 1
#
# It runs tools/sdc_coverage.py over every *.sdc in the commit, so a `get_regs`
# glob that no longer names real RTL is caught at COMMIT time -- not after a
# 40-minute place-and-route, and not never. (The same check runs again inside
# gowin_synth for the case where the RTL moved but the SDC did not.)
#
# CONFIGURATION comes from the repo's own build script: whichever build.sh /
# run*.sh exports GOWIN_RTL_DIRS is the authority, so the search path is
# maintained in exactly ONE place per repo. A repo with no such export is
# skipped silently -- opting in is adding that export.
#
# ⚠ Deliberately NOT gated on "did an .sdc change": the RTL side moves too.
# Renaming an instance in rtl/ with no SDC edit is precisely the RS2 failure
# (ub_rh11 -> ub_rh + ub_rp06) that cost the /70 2.6 ns, so every commit that
# touches EITHER side is checked.

sdc_coverage_gate() {
    local root tool
    root="$(git rev-parse --show-toplevel)" || return 0
    tool="$root/../retrosim-build/tools/sdc_coverage.py"
    [ -f "$tool" ] || return 0                      # standalone clone: skip
    command -v python > /dev/null 2>&1 || return 0

    # Only look at commits that touch RTL or constraints.
    local touched
    touched="$(git diff --cached --name-only --diff-filter=ACMR \
               | grep -E '\.(sdc|sv|v)$' || true)"
    [ -n "$touched" ] || return 0

    local rc=0 checked=0
    # One build script may configure several SDCs; iterate the scripts.
    local bs
    for bs in $(grep -rl 'GOWIN_RTL_DIRS' --include='build.sh' --include='run.sh' \
                --include='run_soc.sh' "$root" 2>/dev/null | sort); do
        local dir dirs
        dir="$(dirname "$bs")"
        dirs="$(grep -oE 'GOWIN_RTL_DIRS="[^"]*"' "$bs" | head -1 \
                | sed 's/.*="//; s/"$//')"
        [ -n "$dirs" ] || continue
        local sdc
        for sdc in $(cd "$dir" && ls ./*.sdc boards/*/*.sdc ./*/*.sdc 2>/dev/null \
                     | grep -v '_gen\.sdc$' | sort -u); do
            checked=$((checked + 1))
            ( cd "$dir" && python "$tool" "$sdc" $dirs ) || rc=1
        done
    done
    if [ "$rc" != 0 ]; then
        echo "pre-commit: SDC COVERAGE FAILED -- a get_regs pattern names RTL" >&2
        echo "  that does not exist, or the search path in GOWIN_RTL_DIRS is" >&2
        echo "  incomplete. Fix the pattern (or the path) before committing." >&2
        echo "  Bypass for a WIP commit with SKIP_GATE=1." >&2
        return 1
    fi
    [ "$checked" -gt 0 ] && echo "pre-commit: sdc-coverage OK ($checked SDC file(s))"
    return 0
}
