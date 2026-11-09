#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Cross-repo duplicate-file report (copy-drift guard).

Groups tracked .sv/.v/.vhd/.vhdl/.py files by basename across every git repo
in the retrosim workspace and reports groups spanning more than one repo,
tagging each IDENTICAL or DRIFTED via CRLF-normalized content hashes.
Vendored third-party trees (cores/) are skipped. Run from anywhere:

    python retrosim-build/tools/dup_scan.py          # workspace = ../.. of this file
    RETROSIM_WS=/path/to/ws python .../dup_scan.py   # explicit workspace root

Same-name hits are not automatically defects (per-core tb_gate.sv wrappers,
per-machine pll_video variants differ deliberately) -- the report is the
starting point for the consolidation triage, not a pass/fail gate.
"""
import hashlib
import io
import os
import subprocess
from collections import defaultdict

WS = os.environ.get('RETROSIM_WS',
                    os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
EXT = ('.sv', '.v', '.vhd', '.vhdl', '.py')
SKIP_DIRS = ('cores/',)  # vendored third-party trees: expected duplicates

repos = sorted(d for d in os.listdir(WS)
               if os.path.isdir(os.path.join(WS, d, '.git'))
               or os.path.isfile(os.path.join(WS, d, '.git')))

groups = defaultdict(list)  # basename -> [(repo, relpath, sha1-12)]
for repo in repos:
    root = os.path.join(WS, repo)
    try:
        out = subprocess.run(['git', '-C', root, 'ls-files'], capture_output=True,
                             text=True, check=True).stdout
    except Exception:
        continue
    for rel in out.splitlines():
        if not rel.lower().endswith(EXT):
            continue
        if any(rel.startswith(sd) for sd in SKIP_DIRS):
            continue
        p = os.path.join(root, rel)
        try:
            data = io.open(p, 'rb').read().replace(b'\r\n', b'\n')
        except OSError:
            continue
        groups[os.path.basename(rel)].append(
            (repo, rel, hashlib.sha1(data).hexdigest()[:12]))

for base in sorted(groups):
    entries = groups[base]
    rset = {r for r, _, _ in entries}
    if len(rset) < 2:
        continue
    hashes = {h for _, _, h in entries}
    tag = 'IDENTICAL' if len(hashes) == 1 else 'DRIFTED'
    print(f'{base}  [{tag}, {len(entries)} copies, {len(rset)} repos]')
    for r, rel, h in sorted(entries):
        print(f'    {h}  {r}/{rel}')
