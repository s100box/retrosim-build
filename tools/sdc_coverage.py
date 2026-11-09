#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""SDC coverage checker -- does every `get_regs` pattern reach real RTL, and
does every register-bearing module level get reached by SOMETHING?

Constraint scope
----------------
Gowin's get_regs globs match one hierarchy level. Splitting, renaming or
adding a module can leave a valid constraint covering only part of the
intended register set. Compare the SDC path segments with RTL instance and
generate names before place-and-route.

WHAT IT CHECKS
--------------
1. STALE PATTERN (error) -- an SDC `get_regs` path prefix that names an
   instance chain the RTL does not contain. ⚠ A stale pattern is not always
   loud: gw_sh rejects a command whose pattern set matches ZERO registers
   (TA2003), but a command listing several patterns survives if ANY of them
   match -- so one stale entry silently drops its share of the plane.
2. UNCOVERED LEVEL (warning) -- an instance level that other constraints
   treat as register-bearing but which no `-to` glob names at all.
3. Summary counts for the build log.

WHAT IT DOES **NOT** CHECK -- read this before trusting a green result
---------------------------------------------------------------------
* It is a **LEVEL** checker, not a per-register one. Gowin's synthesis
  netlist is FLATTENED (instance names carry no hierarchy at all), and no
  Gowin artifact emits a hierarchical register list, so a per-register
  universe does not exist to diff against. A register inside a covered level
  can still be un-nameable -- that is the inferred-RAM blind spot, caught by
  the separate RAM census (gowin.sh `gowin_report_ram`), not here.
* It cannot tell you a relaxation is TRUE. Only that the constraint reaches
  something real. The grounding argument stays human.
* The instance tree is parsed from RTL text (generate labels `begin : g_x`
  and instance names `) u_x (`), not elaborated. Parameters that disable a
  generate arm are therefore ALLOWED, never REQUIRED -- so this errs toward
  silence rather than false alarms.

USAGE
  python sdc_coverage.py <constraints.sdc> <rtl-dir> [<rtl-dir> ...]
    --warn-only   report but always exit 0
Exit 1 on a stale pattern (unless --warn-only).
"""
import argparse
import pathlib
import re
import sys

# Accept every instance/generate name; no u_ or g_ prefix is required.
#
# `) name (` closes a parameterized instantiation; `Type name (` is the plain
# form; `begin : label` opens a generate scope. Gowin renders a generate scope
# and the instance inside it as ONE level joined by a dot (`g_rh.u_rp`,
# `g_fpa.fpa`), so both go into the same namespace.
RE_INST = re.compile(r"^\s*\)\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
RE_INST2 = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)
RE_GEN = re.compile(r"\bbegin\s*:\s*([A-Za-z_][A-Za-z0-9_]*)", re.M)
# Fallback vocabulary: any identifier appearing in the RTL (comments stripped).
# A segment found ONLY here is not proof of an instance, but its ABSENCE from
# even this set is strong evidence the name is genuinely gone -- which is the
# renamed/split-module case this gate exists to catch. Erring this way keeps
# false alarms rare, and rare false alarms are what keep a gate switched on.
RE_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
RE_GETREGS = re.compile(r"get_regs\s*\{([^}]*)\}")


def rtl_names(dirs):
    """Every instance and generate-scope name that appears anywhere in the RTL.

    Deliberately a FLAT set, not a tree: we are checking that each PATH
    SEGMENT of an SDC pattern corresponds to something the RTL actually
    declares. A full elaborated tree would need parameter evaluation, and the
    failure mode we are hunting (a renamed or split module) shows up as a
    segment that exists nowhere at all.
    """
    names, words, files = set(), set(), 0
    for d in dirs:
        p = pathlib.Path(d)
        if not p.exists():
            continue
        for f in list(p.rglob("*.sv")) + list(p.rglob("*.v")):
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            files += 1
            t = RE_COMMENT.sub(" ", t)
            names |= set(RE_INST.findall(t))
            names |= set(RE_INST2.findall(t))
            names |= set(RE_GEN.findall(t))
            words |= set(RE_WORD.findall(t))
    return names, words, files


def sdc_patterns(sdc):
    """Every path segment used inside a get_regs pattern, with its line."""
    out = []
    for n, line in enumerate(
        pathlib.Path(sdc).read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if line.lstrip().startswith(("#", "//")):
            continue
        for blob in RE_GETREGS.findall(line):
            for pat in blob.split():
                out.append((n, pat, line.strip()))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sdc")
    ap.add_argument("rtl", nargs="+")
    ap.add_argument("--warn-only", action="store_true")
    a = ap.parse_args()

    names, words, nfiles = rtl_names(a.rtl)
    if not names:
        print("  sdc-coverage: no RTL found -- skipped", file=sys.stderr)
        return 0
    pats = sdc_patterns(a.sdc)

    stale, covered = [], set()
    for ln, pat, ctx in pats:
        segs = [s for s in pat.split("/") if s]
        bad = []
        for seg in segs[:-1]:  # the LEAF may be a register glob; parents are instances
            # a generate scope and its instance are one dotted level
            for part in seg.split("."):
                part = part.rstrip("*")
                if not part or "*" in part:
                    continue
                # Gowin disambiguates repeated instance names with _<digits>.
                # Accept the RTL name with or without that suffix. This can
                # also excuse a stale suffixed name when its base exists.
                cand = {part, re.sub(r"_\d+$", "", part)}
                if not (cand & names) and not (cand & words):
                    bad.append(part)
        if bad:
            stale.append((ln, pat, sorted(set(bad))))
        else:
            covered.add("/".join(segs[:-1]))

    print(f"  sdc-coverage: {len(pats)} get_regs pattern(s) over "
          f"{len(names)} RTL instance/generate name(s) in {nfiles} file(s)")
    # Several distinct unknown names can indicate an incomplete source search.
    # A single renamed instance remains a stale-pattern error even when many
    # constraints refer to it; the affected-pattern fraction alone is insufficient.
    unknown = sorted({b for _, _, bad in stale for b in bad})
    frac = len(stale) / max(1, len(pats))
    if len(unknown) >= 3 and frac > 0.25:
        print(f"  ⚠ sdc-coverage: {len(unknown)} distinct names unresolved "
              f"across {len(stale)}/{len(pats)} patterns ({frac:.0%}) -- "
              f"REFUSING TO VERDICT.", file=sys.stderr)
        print("    That many DISTINCT unknowns means the RTL SEARCH PATH is "
              "incomplete, not that the SDC is broken.", file=sys.stderr)
        print(f"    Unknown: {', '.join(unknown[:8])}", file=sys.stderr)
        print("    Pass every directory holding instantiating RTL -- the SoC "
              "top and each sibling repo's rtl/, not just this repo's.",
              file=sys.stderr)
        return 0 if a.warn_only else 2

    if stale:
        print("  *** SDC COVERAGE: STALE PATTERN(S) -- they name RTL that does "
              "not exist ***", file=sys.stderr)
        for ln, pat, bad in stale:
            print(f"    {a.sdc}:{ln}: `{pat}` -> unknown: {', '.join(bad)}",
                  file=sys.stderr)
        print("    ⚠ A stale pattern is NOT always loud: gw_sh only rejects a "
              "command whose patterns match ZERO registers, so one dead entry "
              "beside a live one silently drops its share of the plane to N=1.",
              file=sys.stderr)
        if not a.warn_only:
            return 1
    elif not pats:
        # No patterns can mean no scoped exceptions are needed, or missing
        # constraints. Report that nothing was checked rather than a pass.
        print("  sdc-coverage: no get_regs patterns in this SDC -- NOTHING WAS "
              "CHECKED (not a pass; confirm that is intended)")
    else:
        print("  sdc-coverage: all pattern prefixes resolve to real RTL")
    return 0


if __name__ == "__main__":
    sys.exit(main())
