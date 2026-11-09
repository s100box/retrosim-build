#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Check relative links in Markdown files.

By default the repository root and scan path are the current directory. Use
``--root`` to make sibling-repository links internal to a larger workspace,
and pass files or directories to limit the scan. ``--anchors`` additionally
checks Markdown heading fragments using GitHub-style heading slugs.

``--present MANIFEST`` names files that are kept outside git and fetched on
demand (a scan manifest, for example). The first tab-separated field of each
non-comment line is a path relative to ``--root``; a link to one of those
paths counts as resolving whether or not the file has been fetched, so a
fresh clone passes without the download and a mistyped link still fails.

Same-file links -- ``[text](#heading)`` -- are checked too and included in
the summary count.
"""

from __future__ import annotations

import argparse
import html
import os
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote

INLINE = re.compile(r'!?\[[^\]]*\]\(\s*<?([^)<\s]+)>?(?:\s+"[^"]*")?\s*\)')
REFDEF = re.compile(r'^\s{0,3}\[[^\]\[]+\]:\s*<?((?=\S*[/.:])\S+)>?\s*$', re.M)
HEADING = re.compile(r'^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$', re.M)
EXPLICIT_ID = re.compile(r'<a\s+(?:name|id)=["\']([^"\']+)["\']', re.I)
# ⚠ `#' is NOT in this list. A bare `#fragment' is a link to a heading
# in the SAME file, and it is exactly as breakable as a cross-file one.
SKIP_SCHEME = ('http://', 'https://', 'mailto:', 'ftp://', 'data:')


FENCE = re.compile(r'^\s{0,3}(`{3,}|~{3,})')


def strip_code(text: str, spans: bool = True) -> str:
    """Blank out fenced code blocks and inline code spans.

    Source listings can contain expressions such as R[](EXP) that resemble
    Markdown links. Ignore code blocks and spans rather than interpreting
    those expressions as documentation links.

    Lines are replaced, not deleted, so that every other rule that reads this
    text -- headings, reference definitions, both anchored to line starts --
    sees the same line numbering it saw before.
    """
    out, fence = [], None
    for line in text.splitlines():
        marker = FENCE.match(line)
        if fence is None and marker:
            fence = marker.group(1)[0] * 3
            out.append('')
            continue
        if fence is not None:
            if marker and marker.group(1).startswith(fence):
                fence = None
            out.append('')
            continue
        # Heading slugs retain inline code text; their caller uses spans=False.
        out.append(re.sub(r'`[^`]*`', '', line) if spans else line)
    return chr(10).join(out)


def targets(text: str):
    text = strip_code(text)
    for match in INLINE.finditer(text):
        yield match.group(1)
    for match in REFDEF.finditer(text):
        yield match.group(1)


def github_slug(text: str) -> str:
    """Return the slug used by GitHub-compatible Markdown headings."""
    text = html.unescape(text)
    text = re.sub(r'<!--.*?-->', '', text)
    # Strip actual HTML tags, but retain angle-bracketed signal notation such
    # as ``A<17:00>``; CommonMark does not parse a digit-starting bracket as a
    # tag, and GitHub therefore includes ``1700`` in the heading slug.
    text = re.sub(r'</?[A-Za-z][^>]*>', '', text)
    text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
    text = text.replace('`', '').lower()
    text = ''.join(ch for ch in text if ch.isalnum() or ch in ' _-')
    return text.replace(' ', '-')


def anchors(path: Path) -> set[str]:
    # ⚠ A `#` line inside a fence is a comment in the transcribed source, not
    # a heading, and counting it would invent an anchor that no reader can
    # reach -- and shift the `-1`, `-2` suffixes of every real duplicate
    # heading after it.
    text = strip_code(path.read_text(encoding='utf-8', errors='replace'),
                      spans=False)
    result = {unquote(value) for value in EXPLICIT_ID.findall(text)}
    counts: dict[str, int] = {}
    for match in HEADING.finditer(text):
        base = github_slug(match.group(1))
        count = counts.get(base, 0)
        counts[base] = count + 1
        result.add(base if count == 0 else f'{base}-{count}')
    return result


def markdown_files(paths: list[Path]):
    seen: set[Path] = set()
    for path in paths:
        if path.is_file():
            candidates = [path] if path.suffix.lower() == '.md' else []
        elif path.is_dir():
            candidates = (
                item for item in path.rglob('*.md')
                if '.git' not in item.parts
            )
        else:
            candidates = []
        for item in candidates:
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd(),
                        help='boundary for in-tree versus external links')
    parser.add_argument('--anchors', action='store_true',
                        help='also validate fragments on Markdown targets, '
                             'including same-file `#heading` links')
    parser.add_argument('--github-hosted', action='store_true',
                        help='require --root to be a Git checkout root; reject '
                             'links leaving it and targets absent from its '
                             'tracked tree, including case mismatches')
    parser.add_argument('--present', type=Path, action='append', default=[],
                        metavar='MANIFEST',
                        help='file whose first tab-separated column lists '
                             'root-relative paths to treat as existing '
                             '(repeatable)')
    parser.add_argument('paths', nargs='*', type=Path,
                        help='Markdown files/directories to scan (default: root)')
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    scan = [path if path.is_absolute() else root / path
            for path in (args.paths or [Path('.')])]
    broken: list[tuple[str, str]] = []
    bad_anchors: list[tuple[str, str]] = []
    external: list[tuple[str, str]] = []
    anchor_cache: dict[Path, set[str]] = {}
    checked = 0
    tracked = None
    if args.github_hosted:
        top = subprocess.check_output(['git', '-C', str(root), 'rev-parse',
                                       '--show-toplevel'], text=True).strip()
        if Path(top).resolve() != root:
            raise SystemExit('--github-hosted requires --root to be the checkout root')
        tracked = set(subprocess.check_output(
            ['git', '-C', str(root), 'ls-files', '-z']).decode('utf-8').split('\0')) - {''}
    present: set[Path] = set()
    for manifest in args.present:
        for line in manifest.read_text(encoding='utf-8').splitlines():
            field = line.split('\t', 1)[0].strip()
            if field and not field.startswith('#'):
                present.add((root / field).resolve())

    for path in markdown_files(scan):
        if tracked is not None and path.relative_to(root).as_posix() not in tracked:
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        for target in targets(text):
            if target.startswith(SKIP_SCHEME):
                continue
            file_part, separator, fragment = target.partition('#')
            file_part = unquote(file_part)
            if not file_part:
                # A SAME-FILE anchor: `[text](#heading)'. The target file is
                # the one we are reading, so there is nothing to resolve --
                # but the fragment still has to name a heading that exists,
                # and the link still belongs in the population.
                if not (separator and fragment
                        and path.suffix.lower() == '.md'):
                    continue
                checked += 1
                if args.anchors:
                    known = anchor_cache.setdefault(path, anchors(path))
                    if unquote(fragment) not in known:
                        bad_anchors.append((os.path.relpath(path, root),
                                            target))
                continue
            checked += 1
            resolved = (path.parent / file_part).resolve()
            rel = os.path.relpath(path, root)
            if tracked is not None:
                # Use lexical spelling, not Windows filesystem resolution:
                # GitHub paths are case-sensitive, even on a Windows host.
                target_path = posixpath.normpath(posixpath.join(
                    path.relative_to(root).parent.as_posix(), file_part.replace('\\', '/')))
                leaves = (file_part.startswith(('/', '\\')) or target_path == '..'
                          or target_path.startswith('../'))
                exists = (target_path in tracked or target_path == '.' or
                          any(p.startswith(target_path + '/') for p in tracked))
                if leaves or not exists:
                    broken.append((rel, target))
                    continue
            try:
                resolved.relative_to(root)
            except ValueError:
                if not resolved.exists():
                    external.append((rel, target))
                continue
            if not resolved.exists():
                if resolved not in present:
                    broken.append((rel, target))
                continue
            if args.anchors and separator and fragment and resolved.suffix.lower() == '.md':
                known = anchor_cache.setdefault(resolved, anchors(resolved))
                if unquote(fragment) not in known:
                    bad_anchors.append((rel, target))

    print(f'xcheck-links: {checked} relative link(s) checked')
    if external:
        print(f'  note: {len(external)} unresolved link(s) leave {root} (not an error):')
        for rel, target in sorted(set(external))[:10]:
            print(f'    {rel} -> {target}')
    if broken:
        print(f'\n  {len(broken)} BROKEN in-root link(s):', file=sys.stderr)
        for rel, target in sorted(broken):
            print(f'    {rel} -> {target}', file=sys.stderr)
    if bad_anchors:
        print(f'\n  {len(bad_anchors)} BROKEN Markdown anchor(s):', file=sys.stderr)
        for rel, target in sorted(bad_anchors):
            print(f'    {rel} -> {target}', file=sys.stderr)
    if broken or bad_anchors:
        return 1
    print('  gate passed: every checked relative link resolves')
    return 0


if __name__ == '__main__':
    sys.exit(main())
