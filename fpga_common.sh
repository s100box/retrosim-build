#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# fpga_common.sh -- vendor-neutral pieces shared by gowin.sh and vivado.sh.
# SOURCED by both; never source this directly from a repo.

# Bitstream freshness: refuse programming when an RTL or constraint input is
# newer than the artifact. Programming never builds. RETROSIM_RTL_DIRS (or
# GOWIN_RTL_DIRS) lists source directories; constraints are searched near cwd.
# ALLOW_STALE_BITSTREAM=1 explicitly bypasses the check.
# RETROSIM_FS_IGNORE excludes other flows; RETROSIM_FS_TARGET_PATTERNS and
# RETROSIM_FS_TARGET_GLOB distinguish generated inputs for different targets.
# Generated firmware and memory images are outside this timestamp check;
# rebuild after changing them.
retrosim_fs_freshness() {  # <artifact-path> -- 0 = fresh enough, 3 = refused
  local fs="$1" newer n dirs
  dirs="${RETROSIM_RTL_DIRS:-${GOWIN_RTL_DIRS:-.}}"
  echo "[prog] bitstream built $(date -r "$fs" '+%Y-%m-%d %H:%M') -- $fs"
  if [ "${ALLOW_STALE_BITSTREAM:-0}" = 1 ]; then
    echo "[prog] ALLOW_STALE_BITSTREAM=1 -- freshness gate BYPASSED by request"
    return 0
  fi
  # Space-separated find -path globs excluded from the sweep. Use these for
  # another vendor flow's generated artifacts, never shared source inputs.
  local -a prune=()
  local pat
  if [ -n "${RETROSIM_FS_IGNORE:-}" ]; then
    set -f
    for pat in ${RETROSIM_FS_IGNORE}; do prune+=(-not -path "$pat"); done
    set +f
  fi
  # Patterns contain %s for a generated input's target name. Exclude other
  # targets' copies while retaining this target's exact path. TARGET_GLOB
  # narrows the generated-name shape (default *): when hand-written and
  # generated constraints share a directory, choose a prefix that cannot
  # match hand-written sources, e.g. j11_a7lite_* for ./%s.xdc.
  local own mine theirs tglob
  own="${RETROSIM_FS_TARGET:-$(basename "$fs")}"
  own="${own%.*}"
  tglob="${RETROSIM_FS_TARGET_GLOB:-*}"
  if [ -n "${RETROSIM_FS_TARGET_PATTERNS:-}" ]; then
    set -f
    for pat in ${RETROSIM_FS_TARGET_PATTERNS}; do
      case "$pat" in
        *%s*) ;;
        # Skip, do not abort: an unusable pattern leaves the sweep WIDER, so
        # the gate stays conservative.  Name it, because the symptom of a
        # silent skip is an unexplainable stale refusal.
        *) echo "[prog] WARNING: RETROSIM_FS_TARGET_PATTERNS entry lacks %s, ignored: $pat" >&2
           continue ;;
      esac
      theirs="${pat//%s/$tglob}"
      mine="${pat//%s/$own}"
      prune+=( '!' '(' -path "$theirs" '!' -path "$mine" ')' )
    done
    set +f
  fi
  newer=$( { find $dirs -maxdepth 1 \( -name '*.sv' -o -name '*.v' \) "${prune[@]}" -newer "$fs" 2>/dev/null
             find . -maxdepth 3 \( -name '*.sdc' -o -name '*.xdc' \) -not -path './impl*' "${prune[@]}" -newer "$fs" 2>/dev/null; } )
  [ -n "$newer" ] || return 0
  n=$(echo "$newer" | wc -l | tr -d ' ')
  echo "" >&2
  echo "[prog] REFUSING TO PROGRAM A STALE BITSTREAM: $fs" >&2
  echo "  is OLDER than $n RTL/constraint source(s):" >&2
  echo "$newer" | head -8 | sed 's/^/    /' >&2
  [ "$n" -gt 8 ] && echo "    ..." >&2
  echo "  prog/prog-flash NEVER build -- synthesize first, or load the older" >&2
  echo "  machine deliberately with ALLOW_STALE_BITSTREAM=1." >&2
  return 3
}
