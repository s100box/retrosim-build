#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Timing RELATION CENSUS -- what multiple of the period STA actually applied.

Companion to timing_signoff.py (same directory, same consumers). Sign-off
answers "did it close"; the census answers a different and less-asked
question: **for each path, which cadence did the tool believe?**

WHY THIS EXISTS
---------------
An SDC multicycle is a CLAIM about the design: "this launch reaches this
capture N clocks later." The claim can be wrong in two directions, and they
are not symmetric:

  * UNDER-scoped (N too small, or no exception at all) -- STA times a
    multi-clock path as one clock. Costs closure and PnR effort; NEVER costs
    silicon. Loud: it shows up as negative slack.
  * OVER-scoped (N too large, or a glob that swallows a genuinely
    single-cycle sink) -- STA relaxes a path the hardware needs in one clock.
    This is the timing-doc section 2.4 SILICON TRAP: it signs off and then
    fails on the board. SILENT: an over-scoped path reports POSITIVE slack by
    construction, so no sweep, no ask ladder and no sign-off gate can find it.

The census is the cheap check for the silent direction. It reports the
Relation the tool resolved per path -- including which exception won where
several globs overlap, which is the part nobody can predict by reading the
SDC -- and it is most valuable DIFFED BETWEEN BUILDS: a relation that moves
with no SDC edit means a glob started matching something new (a renamed
register, a fresh generate arm, a retimed net).

WHAT IT CANNOT SEE (state this wherever you quote its output)
-------------------------------------------------------------
  * Paths outside the report. Gowin's report_timing emits `-max_paths N` per
    group (25 by default). The census covers exactly what the report carries;
    raise -max_paths in the flow .tcl for a deeper one. A census is therefore
    a sample of the CRITICAL paths, not a proof about all of them.
  * Consequence for --diff: it reports families whose RELATION moved, and
    deliberately says nothing about families that entered or left the sample.
    Those come and go on every build as slack shifts the worst-N cut, so
    reporting them would be pure noise -- but it does mean "no family changed
    its relation" is NOT the same as "nothing changed". Read it as: no glob
    started matching differently. Slack movement is timing_signoff's job.

    Inspect the full census and sign-off report for newly critical families;
    --diff does not flag a family that enters the sample with negative slack.
  * Sinks `get_regs` cannot name -- inferred-RAM address/CE pins (doc section
    2.8). They have no nameable endpoint, so they can carry no exception and
    appear under no glob. They are permanently N=1 and the only lever is the
    period.

Usage:
  timing_relation_census.py <tr_content.html> [--period NS] [--json OUT]
  timing_relation_census.py <new.html> --diff <old.html>
"""

import argparse
import collections
import html
import json
import os
import re
import sys

# The Path Slacks summary tables carry one row per path, nine columns:
#   Path Number | Path Slack | From Node | To Node | From Clock | To Clock |
#   Relation | Clock Skew | Data Delay
_COLS = ["num", "slack", "frm", "to", "fclk", "tclk", "relation", "skew", "delay"]


def _text_lines(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        raw = fh.read()
    txt = html.unescape(re.sub(r"<[^>]+>", "\n", raw))
    return [ln.strip() for ln in txt.split("\n") if ln.strip()]


def parse_paths(path):
    """Every row of every Path Slacks table, as dicts."""
    lines = _text_lines(path)
    rows, i = [], 0
    num_re = re.compile(r"^\d+$")
    flt_re = re.compile(r"^-?\d+\.\d+$")
    while i < len(lines) - 9:
        # A row starts at a bare integer (the path number) followed by a
        # float slack, two node names, and two clock names.
        if (num_re.match(lines[i]) and flt_re.match(lines[i + 1])
                and "/" in lines[i + 2] and "/" in lines[i + 3]
                and lines[i + 4].startswith("clk") and lines[i + 5].startswith("clk")):
            rec = dict(zip(_COLS, lines[i:i + 9]))
            try:
                rec["slack"] = float(rec["slack"])
                rec["relation"] = float(rec["relation"])
                rec["delay"] = float(rec["delay"])
            except ValueError:
                i += 1
                continue
            rows.append(rec)
            i += 9
        else:
            i += 1
    return rows


def family(node):
    """Collapse an instance path to the family a get_regs glob would name.

    `u_membox/g_ube.u_ube/dma_wdata_8_s0/CE` -> `u_membox/g_ube.u_ube/dma_wdata`
    `u_cpu/uword_q_26_s0/Q`                  -> `u_cpu/uword_q`
    Gowin's PnR suffixes (_<bit>_s<n>) and the pin are dropped; the hierarchy
    is kept, because hierarchy is exactly what a one-level glob can and
    cannot reach.
    """
    parts = node.split("/")
    if len(parts) > 1 and parts[-1].isupper():   # a pin: Q, CE, D, RESET, ...
        parts = parts[:-1]
    leaf = parts[-1] if parts else node
    leaf = re.sub(r"_s\d+$", "", leaf)           # the placer's split suffix
    leaf = re.sub(r"(\[\d+\])?_\d+$", "", leaf)  # the bit index
    return "/".join(parts[:-1] + [leaf])


def census(rows, period=None):
    """(launch family, sink family, relation) -> count, worst slack, worst delay."""
    agg = {}
    for r in rows:
        key = (family(r["frm"]), family(r["to"]), r["relation"], r["fclk"], r["tclk"])
        cur = agg.get(key)
        if cur is None:
            agg[key] = {"n": 1, "worst": r["slack"], "delay": r["delay"]}
        else:
            cur["n"] += 1
            if r["slack"] < cur["worst"]:
                cur["worst"] = r["slack"]
                cur["delay"] = r["delay"]
    out = []
    for (frm, to, rel, fclk, tclk), v in agg.items():
        n_clocks = None
        if period:
            n_clocks = round(rel / period, 3)
        out.append({
            "from": frm, "to": to, "relation_ns": rel, "n_clocks": n_clocks,
            "from_clock": fclk, "to_clock": tclk,
            "paths": v["n"], "worst_slack": v["worst"], "data_delay": v["delay"],
        })
    out.sort(key=lambda d: (d["worst_slack"], -d["paths"]))
    return out


def fmt(entries, period):
    w = []
    w.append(f"{'N':>4}  {'rel(ns)':>8}  {'clks':>5}  {'worst':>8}  {'delay':>7}  from -> to")
    w.append("-" * 100)
    for e in entries:
        clks = f"{e['n_clocks']:g}" if e["n_clocks"] is not None else "?"
        w.append(f"{e['paths']:>4}  {e['relation_ns']:>8.3f}  {clks:>5}  "
                 f"{e['worst_slack']:>8.3f}  {e['data_delay']:>7.3f}  "
                 f"{e['from']} -> {e['to']}")
    return "\n".join(w)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report", help="impl_<base>/pnr/<base>_tr_content.html")
    ap.add_argument("--period", type=float, default=None,
                    help="clock period in ns, to render Relation as a clock count")
    ap.add_argument("--json", default=None, help="write the census as JSON")
    ap.add_argument("--diff", default=None,
                    help="a previous report: print only families whose relation MOVED")
    args = ap.parse_args()

    for f in (args.report, args.diff):
        if f is not None and not os.path.exists(f):
            print(f"timing_relation_census: no such report: {f}\n"
                  f"  (impl_<base>.prev/ keeps ONE generation -- a second "
                  f"rebuild rotates it away)", file=sys.stderr)
            return 2
    rows = parse_paths(args.report)
    if not rows:
        print("timing_relation_census: no path rows found -- is this a "
              "*_tr_content.html?", file=sys.stderr)
        return 2
    cur = census(rows, args.period)

    if args.diff:
        old = {(e["from"], e["to"]): e for e in census(parse_paths(args.diff), args.period)}
        moved = []
        for e in cur:
            o = old.get((e["from"], e["to"]))
            if o and abs(o["relation_ns"] - e["relation_ns"]) > 1e-6:
                moved.append((e, o))
        if not moved:
            print("relation census: no family changed its relation.")
            return 0
        print("!! RELATION CHANGED (a glob started matching differently):")
        for e, o in moved:
            print(f"  {o['relation_ns']:.3f} -> {e['relation_ns']:.3f} ns   "
                  f"{e['from']} -> {e['to']}")
        return 1

    print(f"relation census: {len(rows)} path row(s), "
          f"{len(cur)} (launch, sink, relation) famil(ies)")
    print("!! SAMPLE, NOT PROOF: covers only the paths report_timing emitted "
          "(-max_paths per group).")
    print(fmt(cur, args.period))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(cur, fh, indent=2)
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
