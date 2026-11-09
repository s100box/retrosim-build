#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Gowin timing sign-off -- the SHARED gate for every retrosim FPGA repo.

Called by each repo's fpga/build.sh after PnR (this file lives in the
retrosim-build sibling; consumers invoke it by relative path, e.g.
`python ../../retrosim-build/tools/timing_signoff.py <trc> <sdc>`).

Parses impl_<base>/pnr/<base>_tr_content.html and applies the sign-off rules
from ts804fpga/doc/gowin-timing-closure.md:

  1. Gate on the per-clock "Total Negative Slack Summary" -- the endpoint
     counts after SDC exceptions, Setup AND Hold rows -- never the raw
     setup-only violated-endpoints count (that number is printed as an
     informational residual line only).
  2. Report each clock's constraint vs actual Fmax (the PnR margin), so
     run-to-run drift toward the ~1 ns "re-synth lottery" zone is visible.
  3. If the SDC declares PATH exceptions (multicycle / false path / min-max
     delay), fail when the Timing Exceptions Report shows none matched --
     Gowin ignores malformed exceptions silently, and a dead exception means
     timing result is invalid. set_clock_groups and set_false_path are
     excluded from this count: their paths are removed from analysis, so
     report_exceptions does not list them. The SDC health table checks
     whether those constraints are active.
  4. If the report carries the "SDC Constraints" health table (TC_* rows with
     an Actived status), fail on any non-Actived row -- strictly stronger
     than 3 (also catches a dead create_generated_clock or a glob that
     matched nothing).

Deliberate-overconstraint waiver (the v180 "lazy-placer" recipe): --ship MHZ
waives the ship clock's SETUP TNS if and only if the reported actual Fmax
still clears the silicon ship clock; Hold violations and every other clock
still gate. Without --ship any nonzero TNS row fails.

Usage: timing_signoff.py <tr_content.html> <constraints.sdc>
                         [--ship MHZ] [--ship-clock NAME]
Exit 0 = timing met; 1 = violations, Fmax below ship, or dead constraints;
2 = parse failure.
"""

import argparse
import re
import sys


def tokens(html_path):
    text = open(html_path, encoding="utf-8", errors="replace").read()
    stripped = re.sub(r"<[^>]+>", "|", text)
    return [t.strip() for t in stripped.split("|") if t.strip()]


def parse_fmax(toks):
    """Max Frequency Summary rows: (clock, constraint_mhz, actual_mhz)."""
    rows = []
    try:
        i = toks.index("Max Frequency Summary:")
    except ValueError:
        return rows, []
    end = toks.index("Total Negative Slack Summary:", i)
    j = i
    while j < end:
        m = re.fullmatch(r"([\d.]+)\(MHz\)", toks[j])
        if m and j + 1 < end and re.fullmatch(r"([\d.]+)\(MHz\)", toks[j + 1]):
            rows.append((toks[j - 1], float(m.group(1)),
                         float(re.fullmatch(r"([\d.]+)\(MHz\)", toks[j + 1]).group(1))))
            j += 2
            continue
        j += 1
    untimed = [re.fullmatch(r"No timing paths to get frequency of (\S+?)!?", t).group(1)
               for t in toks[i:end] if t.startswith("No timing paths to get frequency")]
    return rows, untimed


def parse_tns(toks):
    """TNS Summary rows: (clock, analysis, tns_ns, endpoints)."""
    i = toks.index("Total Negative Slack Summary:")
    end = toks.index("Timing Details", i)
    j = toks.index("Number of Endpoints", i) + 1
    rows = []
    while j + 3 < end:
        clock, analysis, tns, count = toks[j:j + 4]
        if not re.fullmatch(r"-?[\d.]+", tns) or not count.isdigit():
            break
        rows.append((clock, analysis, float(tns), int(count)))
        j += 4
    return rows


def parse_cross_clock_rows(toks):
    """Path Slacks Table rows whose launch and latch clocks DIFFER:
    (slack_ns, from_node, to_node, from_clock, to_clock).

    ⚠ Gowin's per-clock "Total Negative Slack Summary" buckets only
    SAME-clock paths, so a cross-domain violation leaves every TNS row at
    0.000 while the design misses timing. The Path Slacks Table is
    POST-exception (a multicycled path appears with its adjusted slack;
    a false-pathed pair does not appear at all), so any NEGATIVE
    cross-clock row here is a real violation and gates. Absent table
    (older report shapes) -> None, check skipped.
    """
    try:
        i = toks.index("Path Slacks Table:")
    except ValueError:
        return None
    try:
        end = toks.index("Hold Paths Table", i)
    except ValueError:
        end = len(toks)
    rows = []
    j = i
    while j + 8 < end:
        if (toks[j].isdigit() and re.fullmatch(r"-?[\d.]+", toks[j + 1])
                and "/" in toks[j + 2] and "/" in toks[j + 3]
                and ":[" in toks[j + 4] and ":[" in toks[j + 5]):
            fclk = toks[j + 4].split(":")[0]
            tclk = toks[j + 5].split(":")[0]
            if fclk != tclk:
                rows.append((float(toks[j + 1]), toks[j + 2], toks[j + 3],
                             fclk, tclk))
            j += 9
            continue
        j += 1
    return rows


def parse_raw_setup_violated(toks):
    """The raw 'Setup Violated Endpoints' count -- informational ONLY.

    It includes residuals the SDC exceptions legitimately discount (false-
    pathed reset-CDC, multicycle phantoms), so it is never gated on; repos
    that false-path quasi-static crossings like seeing it printed.
    """
    return next((toks[i + 1] for i, t in enumerate(toks)
                 if "Setup Violated Endpoints" in t and i + 1 < len(toks)), None)


def parse_exceptions_matched(toks):
    """True if any report_exceptions analysis matched at least one path."""
    try:
        i = toks.index("Timing Exceptions Report:")
    except ValueError:
        return False
    try:
        end = toks.index("Timing Constraints Report:", i)
    except ValueError:
        end = len(toks)
    block = toks[i:end]
    return any(re.fullmatch(r"Path\d+", t) for t in block)


def parse_sdc_health(toks):
    """SDC Constraints health rows: (tc_type, status, constraint_text).

    Not every report shape carries the table; an empty list means "absent,
    skip the check" (the exceptions-report check in parse_exceptions_matched
    still applies).
    """
    return [(toks[i], toks[i + 1], toks[i + 2]) for i, t in enumerate(toks)
            if re.fullmatch(r"TC_[A-Z_]+", t) and i + 2 < len(toks)]


def sdc_path_exception_count(sdc_path):
    """Count PATH exceptions only.

    Not counted (invisible to report_exceptions -- their verification is the
    CDC audit / Actived table, not this gate): set_clock_groups and EVERY
    set_false_path. A false path removes its paths from analysis, so Gowin's
    report_exceptions never lists them -- not even register-to-register ones.
    Counting false paths would reject valid SDCs containing only false paths
    and no multicycle/min/max-delay exception to populate the report.
    """
    count = 0
    for line in open(sdc_path, encoding="utf-8", errors="replace"):
        stmt = line.split("//")[0].split("#")[0].strip()
        if re.match(r"(set_multicycle_path|set_max_delay|set_min_delay)\b",
                    stmt):
            count += 1
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tr_content")
    ap.add_argument("sdc")
    ap.add_argument("--ship", type=float, default=None,
                    help="silicon clock (MHz) the ship-clock must clear; "
                         "waives ship-clock SETUP TNS under a deliberate "
                         "SDC over-constraint")
    ap.add_argument("--ship-clock", default="clk_core")
    args = ap.parse_args()

    try:
        toks = tokens(args.tr_content)
        fmax_rows, untimed = parse_fmax(toks)
        tns_rows = parse_tns(toks)
    except (ValueError, OSError) as exc:
        print(f"  sign-off: cannot parse {args.tr_content}: {exc}",
              file=sys.stderr)
        return 2
    if not tns_rows:
        print(f"  sign-off: no TNS summary rows found in {args.tr_content}",
              file=sys.stderr)
        return 2

    ok = True

    actual_by_clock = {}
    for clock, constraint, actual in fmax_rows:
        actual_by_clock[clock] = actual
        margin_ns = 1000.0 / constraint - 1000.0 / actual
        line = (f"  {clock}: constraint {constraint:.3f} MHz, actual Fmax "
                f"{actual:.3f} MHz (margin {margin_ns:+.2f} ns)")
        if args.ship is not None and clock == args.ship_clock:
            ship_margin = 1000.0 / args.ship - 1000.0 / actual
            line += f"; ship {args.ship:.3f} MHz (margin {ship_margin:+.2f} ns)"
        print(line)
        if args.ship is None and 0 <= margin_ns < 1.0:
            print(f"  {clock}: WARNING margin < 1 ns -- PnR re-synth lottery zone")
    for clock in untimed:
        print(f"  {clock}: no timed paths")

    ship_ok = None
    if args.ship is not None:
        actual = actual_by_clock.get(args.ship_clock)
        if actual is None:
            print(f"  {args.ship_clock}: not in the Max Frequency Summary -- "
                  f"cannot verify the {args.ship:.3f} MHz ship clock")
            ship_ok = False
            ok = False
        else:
            ship_ok = actual >= args.ship
            if not ship_ok:
                print(f"  {args.ship_clock}: actual Fmax {actual:.3f} MHz is BELOW "
                      f"the {args.ship:.3f} MHz silicon ship clock")
                ok = False
            elif 1000.0 / args.ship - 1000.0 / actual < 1.0:
                print(f"  {args.ship_clock}: WARNING ship margin < 1 ns -- "
                      f"PnR re-synth lottery zone")

    waived = []
    bad = []
    for clock, analysis, tns, count in tns_rows:
        if count == 0:
            continue
        if (ship_ok and clock == args.ship_clock and analysis == "Setup"):
            waived.append((clock, analysis, tns, count))
        else:
            bad.append((clock, analysis, tns, count))
    for clock, analysis, tns, count in waived:
        print(f"  {clock} {analysis}: TNS {tns:.3f} ns over {count} endpoints -- "
              f"waived (deliberate over-constraint; actual Fmax clears the "
              f"{args.ship:.3f} MHz ship clock)")
    if bad:
        ok = False
        for clock, analysis, tns, count in bad:
            print(f"  {clock} {analysis}: TNS {tns:.3f} ns over {count} endpoints")
    elif not waived:
        clocks = sorted({c for c, _, _, _ in tns_rows})
        print(f"  TNS: 0 violated endpoints across {len(tns_rows)} analyzes "
              f"({', '.join(clocks)})")

    raw = parse_raw_setup_violated(toks)
    if raw is not None and raw.isdigit() and int(raw) > 0:
        print(f"  raw Setup Violated Endpoints: {raw} (residuals the SDC "
              f"exceptions discount -- informational, not gated)")

    cross = parse_cross_clock_rows(toks)
    if cross is not None:
        neg = [r for r in cross if r[0] < 0]
        if neg:
            ok = False
            worst = sorted(neg)[:5]
            print(f"  CROSS-CLOCK VIOLATIONS: {len(neg)} negative inter-clock "
                  f"path(s) in the Path Slacks Table -- INVISIBLE to the "
                  f"per-clock TNS summary above (it buckets same-clock paths "
                  f"only); worst:")
            for slack, fn, tn, fc, tc in worst:
                print(f"    {slack:+.3f} ns  {fc} -> {tc}  {fn} -> {tn}")
        elif cross:
            worst = min(r[0] for r in cross)
            print(f"  cross-clock paths: {len(cross)} inter-clock row(s) in "
                  f"the Path Slacks Table, worst slack {worst:+.3f} ns")

    declared = sdc_path_exception_count(args.sdc)
    if declared and not parse_exceptions_matched(toks):
        ok = False
        print(f"  SDC declares {declared} path exception(s) but the Timing "
              f"Exceptions Report matched no paths -- dead exception "
              f"(silently ignored by Gowin)")

    health = parse_sdc_health(toks)
    dead = [(t, s, c) for t, s, c in health if s != "Actived"]
    if dead:
        ok = False
        for tc, status, constraint in dead:
            print(f"  DEAD SDC constraint ({tc} {status}): {constraint}")
    elif health:
        print(f"  SDC constraints: {len(health)} in report, all Actived")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
