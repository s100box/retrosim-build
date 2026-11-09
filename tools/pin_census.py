#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Workspace census of UNCONNECTED MODULE PINS (Verilator PINMISSING).

WHY THIS EXISTS. An unconnected module INPUT is silent in everything this
workspace runs. iverilog has no missing-pin diagnostic at all; Verilator's
PINMISSING is waived (-Wno-PINMISSING) by every sim harness here, and even
un-waived it is a warning that the harnesses' -Wno-fatal would not fail on. So
adding a port to a shared-RTL module (hh-sdram, hh-6502, hh-6809, hh-sdcard,
hh-hdmi, v180 ...) is a source-incompatible change to ~10 sibling repos that
NOTHING detects. It cost a month once: hh-sdram's host16 split gave
z180_mem_subsys a per-byte `wstrb_i`, hh-c128's two machine tops never
connected it, and because the backend's write enable is
`do_write & req_wstrb_i[0]` the C128 and C64 took NO RAM WRITES AT ALL --
in every bench, behind a blank screen (hh-c128 PROGRESS 6.27).

HOW IT WORKS, and why it needs no cooperation from any repo. CMake's Verilator
integration leaves a `verilator_args.txt` next to every bench it builds: the
exact argument vector of a build that really ran. This replays each one with
--lint-only and -Werror-PINMISSING, so no repo's harness has to change and
nothing is rebuilt. Direction is reported per pin, because that is the whole
triage: an omitted OUTPUT is cosmetic, an omitted INPUT silently becomes x
(iverilog) or 0 (Verilator --x-assign 0).

WHAT IT CANNOT DO -- read this before believing a clean run:
  * It only sees benches that have been BUILT at least once on this machine.
    A repo nobody has verilated here contributes nothing and is not counted.
  * A recorded arg file goes stale when sources move or are renamed; those
    builds are listed under "could not be replayed" and are NOT covered. A run
    with a long stale list is a partial census, so it prints the count.
  * PINMISSING does not distinguish a deliberate omission from a mistake. Most
    real hits are legitimate -- a feature compiled out by a parameter
    (`DELUA_EN = 0`), or a port the library documents as "may be left
    unconnected". The fix for those is `.pin()`, explicitly empty: it says
    "deliberately unused" where omission says nothing.
  * Testbenches are waived by default (--waive-tb): a bench instantiates a DUT
    to exercise one thing and legitimately ignores outputs it does not score.

TRAP, paid for in a false clean: Verilator prints WINDOWS paths in its
messages, complete with a drive-letter colon and backslashes. A file regex of
"anything but a colon" matches `C` and drops every hit. The first version of
this script reported a spotless workspace for exactly that reason. If you
change PIN_RE, test it against a message with a `C:\\Users\\...` path first.

Usage:
    python pin_census.py [WORKSPACE_ROOT] [--no-waive-tb] [--oss DIR]
"""
import argparse
import collections
import os
import re
import subprocess
import sys
import tempfile

# The path group must be non-greedy up to the .sv/.v -- see the TRAP note above.
PIN_RE = re.compile(
    r"%Error-PINMISSING: (?P<f>.+?\.s?v):(?P<l>\d+):\d+: "
    r"Instance has missing pin: '(?P<p>\w+)'")
DECL_RE = re.compile(r"^\s*\d+ \|\s*(input|output|inout)\b")

# Args that belong to the CMake build flow, not to a lint.
DROP_WITH_ARG = {'--prefix', '--Mdir', '--make', '--compiler', '--top-module',
                 '-o', '-j'}
DROP_ALONE = {'--cc', '--binary', '-Wno-PINMISSING'}

WAIVER = ('`verilator_config\n'
          'lint_off -rule PINMISSING -file "*tb_*.sv"\n')


def load(path):
    """The verilator argument vector recorded in one verilator_args.txt."""
    items = open(path, encoding='utf-8', errors='replace').read().strip().split(';')
    for i, a in enumerate(items):
        if a.endswith('verilator_bin.exe') or a.endswith('verilator_bin'):
            items = items[i + 1:]
            break
    else:
        return None
    out = []
    skip = False
    for a in items:
        if skip:
            skip = False
            continue
        if a in DROP_WITH_ARG:
            skip = True
            continue
        if a in DROP_ALONE:
            continue
        out.append(a)
    return out


def parse(out):
    """(file, line, pin, direction) per PINMISSING. The direction comes from
    the 'Location of port declaration' block Verilator prints underneath."""
    lines = out.splitlines()
    hits = []
    for i, ln in enumerate(lines):
        m = PIN_RE.search(ln)
        if not m:
            continue
        direction = '?'
        for j in range(i + 1, min(i + 8, len(lines))):
            dm = DECL_RE.match(lines[j])
            if dm:
                direction = dm.group(1)
                break
        hits.append((m.group('f').replace(os.sep, '/'), int(m.group('l')),
                     m.group('p'), direction))
    return hits


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('root', nargs='?', default='.', help='workspace root')
    ap.add_argument('--oss', default=os.path.expanduser('~/oss-cad-suite'),
                    help='oss-cad-suite install (verilator_bin + its DLLs)')
    ap.add_argument('--no-waive-tb', action='store_true',
                    help='report testbench instantiations too')
    args = ap.parse_args()

    root = os.path.abspath(args.root).replace(os.sep, '/')
    oss = os.path.abspath(args.oss).replace(os.sep, '/')
    exe = oss + '/bin/verilator_bin.exe'
    if not os.path.exists(exe):
        exe = oss + '/bin/verilator_bin'
    if not os.path.exists(exe):
        print('no verilator_bin under %s' % oss, file=sys.stderr)
        return 2

    env = dict(os.environ)
    env['VERILATOR_ROOT'] = oss + '/share/verilator'
    env['PATH'] = oss + '/bin;' + oss + '/lib;' + env.get('PATH', '')

    vlt = None
    if not args.no_waive_tb:
        fd, vlt = tempfile.mkstemp(suffix='.vlt')
        os.write(fd, WAIVER.encode())
        os.close(fd)
        vlt = vlt.replace(os.sep, '/')

    recorded = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if 'verilator_args.txt' in filenames:
            recorded.append(dirpath.replace(os.sep, '/') + '/verilator_args.txt')

    seen = set()
    jobs = []
    for f in sorted(recorded):
        vec = load(f)
        if not vec:
            continue
        srcs = tuple(a for a in vec if a.endswith(('.sv', '.v')))
        top = next((vec[i + 1] for i, a in enumerate(vec) if a == '--top'), '?')
        repo = f[len(root) + 1:].split('/')[0]
        if (repo, top, srcs) in seen:
            continue
        seen.add((repo, top, srcs))
        jobs.append((repo, top, vec))

    print('%d recorded bench build(s), %d unique' % (len(recorded), len(jobs)))
    hits = collections.defaultdict(list)
    stale = []
    for repo, top, vec in jobs:
        cmd = [exe, '--lint-only', '-Werror-PINMISSING']
        if vlt:
            cmd.append(vlt)
        try:
            r = subprocess.run(cmd + vec, capture_output=True, text=True,
                               env=env, timeout=900)
        except Exception as exc:                      # noqa: BLE001
            stale.append((repo, top, str(exc)[:110]))
            continue
        out = r.stdout + r.stderr
        found = parse(out)
        if found:  # do not create an empty repo key -- it reads as a report
            hits[repo].extend(found)
        other = [l for l in out.splitlines()
                 if l.startswith('%Error') and 'PINMISSING' not in l]
        if other and not found:
            stale.append((repo, top, other[0][:110]))

    print('')
    print('=== MISSING PINS%s ===' % ('' if args.no_waive_tb else ' (tb_*.sv waived)'))
    if not hits:
        print('  none -- but see the stale list below before calling that clean')
    for repo in sorted(hits):
        rows = sorted(set(hits[repo]))
        ins = [r for r in rows if r[3] in ('input', 'inout')]
        print('')
        print('%s -- %d site(s), %d on an INPUT/INOUT' % (repo, len(rows), len(ins)))
        for f, ln, pin, direction in rows:
            short = f[len(root) + 1:] if f.startswith(root) else f
            print('    %-7s %-28s %s:%d' % (direction, pin, short, ln))

    if stale:
        print('')
        print('=== NOT COVERED: %d build(s) could not be replayed ===' % len(stale))
        print('    (stale arg file -- sources moved or renamed since that build)')
        for repo, top, msg in stale:
            print('  %-12s %-26s %s' % (repo, top, msg))
    return 0


if __name__ == '__main__':
    sys.exit(main())
