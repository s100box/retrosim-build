#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Find registers with an ASYNCHRONOUS reset that index or gate a memory array.

WHY A TEXT SCAN AND NOT JUST THE DRC. The authoritative check is Vivado's
REQP-1839/1840 (see bram_async_census.sh), but it only reaches designs that
synthesize under Vivado, and only arrays the tool maps to *block* RAM. Most of
this fleet is Gowin-only, several designs need per-board packages and defines to
elaborate, and a Gowin BSRAM can land in Xilinx LUTRAM where the rule is silent.
So this scan runs everywhere, with no toolchain at all, and its job is to
produce the candidate list a human then judges.

WHAT IT CANNOT DO, so nobody reads a clean run as proof:
  * It is per-file. A driving register in a PARENT module (a reset-release
    synchroniser gating a child's RAM writes -- the single worst case found so
    far) is invisible here. Only the real-top DRC sees those.
  * It does not evaluate expressions; an index built through intermediate wires
    is followed one hop at most.
  * It cannot tell a block RAM from a small array that will end up in flops.
Treat a hit as "look at this", and a miss as "this file says nothing", never as
a pass.
"""
import argparse
import os
import re
import sys

# `always_ff @(posedge clk or negedge rst_n)` / `always @(posedge c or posedge r)`
ASYNC_HDR = re.compile(
    r'always(?:_ff)?\s*@\s*\(\s*(?:pos|neg)edge\s+\w+\s+or\s+(?:pos|neg)edge\s+(\w+)\s*\)')
# a memory array declaration: `logic [15:0] rom[65536];` / `reg [7:0] m [0:255];`
ARRAY_DECL = re.compile(
    r'^\s*(?:\(\*[^*]*\*\)\s*)?(?:logic|reg|bit|wire)\s*(?:signed\s*)?'
    r'(?:\[[^\]]+\]\s*)?(\w+)\s*\[\s*[^\]]+\s*\]\s*;', re.M)
IDENT = re.compile(r'[A-Za-z_]\w*')

KEYWORDS = {
    'begin', 'end', 'if', 'else', 'case', 'endcase', 'posedge', 'negedge', 'or',
    'and', 'not', 'logic', 'reg', 'wire', 'bit', 'always', 'always_ff', 'assign',
    'unique', 'priority', 'default', 'for', 'int', 'signed', 'unsigned',
}


def block_body(text, start):
    """The text of the always block beginning at `start` (brace/begin matching
    is not reliable here, so take to the matching `end` by depth counting on
    begin/end word boundaries; a block with no begin is a single statement)."""
    m = re.compile(r'\bbegin\b').search(text, start)
    nl = text.find('\n', start)
    if m is None or (nl != -1 and m.start() > text.find(';', start) != -1 and m.start() > nl):
        end = text.find(';', start)
        return text[start:end + 1] if end != -1 else text[start:start + 400]
    depth = 0
    for tok in re.finditer(r'\bbegin\b|\bend\b', text[m.start():]):
        if tok.group(0) == 'begin':
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                return text[start:m.start() + tok.end()]
    return text[start:]


def async_assigned(text):
    """Signals assigned inside an always block with an asynchronous reset."""
    out = {}
    for m in ASYNC_HDR.finditer(text):
        body = block_body(text, m.start())
        rst = m.group(1)
        for a in re.finditer(r'(\w+)\s*(?:\[[^\]]*\])?\s*<=', body):
            out.setdefault(a.group(1), rst)
    return out


def array_uses(text, arrays):
    """(array, kind, identifiers) for every use of a declared array."""
    uses = []
    for name in arrays:
        for m in re.finditer(re.escape(name) + r'\s*\[([^\]]+)\]', text):
            idx = m.group(1)
            # write if an assignment operator follows the closing bracket
            tail = text[m.end():m.end() + 8]
            kind = 'write' if re.match(r'\s*<?=', tail) else 'read'
            ids = {i for i in IDENT.findall(idx) if i not in KEYWORDS}
            # a write's enable is whatever the guarding `if (...)` tests
            if kind == 'write':
                line_start = text.rfind('\n', 0, m.start())
                guard = text[max(0, line_start - 200):m.start()]
                g = re.findall(r'if\s*\(([^)]*)\)', guard)
                if g:
                    ids |= {i for i in IDENT.findall(g[-1]) if i not in KEYWORDS}
            uses.append((name, kind, ids))
    return uses


def scan_file(path):
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return []
    text = re.sub(r'//[^\n]*', '', text)
    text = re.sub(r'/\*.*?\*/', '', text, flags=re.S)
    arrays = set(ARRAY_DECL.findall(text))
    if not arrays:
        return []
    aregs = async_assigned(text)
    if not aregs:
        return []
    hits = []
    for name, kind, ids in array_uses(text, arrays):
        for i in sorted(ids & set(aregs)):
            hits.append((name, kind, i, aregs[i]))
    return sorted(set(hits))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('roots', nargs='+', help='directories to scan')
    ap.add_argument('--quiet-clean', action='store_true',
                    help='only print files with hits')
    args = ap.parse_args()

    total = 0
    for root in args.roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (
                '.git', '.repo', 'build', 'impl', 'work', 'node_modules',
                '__pycache__', '.scratch', 'test-results')
                and not d.startswith('impl_')]
            for fn in sorted(filenames):
                if not fn.endswith(('.sv', '.v')):
                    continue
                p = os.path.join(dirpath, fn)
                hits = scan_file(p)
                if not hits:
                    continue
                rel = os.path.relpath(p)
                print(rel)
                for name, kind, sig, rst in hits:
                    print('    %-22s %-5s <- %-24s (async reset %s)'
                          % (name, kind, sig, rst))
                total += len(hits)
    print('\n%d candidate(s). A hit is "look at this", not a verdict; a clean '
          'run proves nothing about cross-module drivers.' % total)
    return 0


if __name__ == '__main__':
    sys.exit(main())
