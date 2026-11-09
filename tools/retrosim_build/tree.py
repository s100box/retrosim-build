# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Configurable source hygiene with the shared Markdown link parser."""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import runpy
import subprocess
from urllib.parse import unquote
from .toolchain import ROOT

SPDX_EXT = {".md", ".sh", ".py", ".sv", ".svh", ".v", ".tcl", ".rs", ".toml", ".xdc", ".ps1", ".f", ".ninja"}
BINARY = {".png", ".pdf", ".zip", ".bin", ".bit", ".gz", ".xlsx", ".sr"}


def tracked(root):
    return subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"], text=True).split("\0")[:-1]


def check(root, paths=(), policy=None):
    root = Path(root).resolve()
    policy = policy or {}
    paths = paths or tracked(root)
    parser = runpy.run_path(str(ROOT / "tools/xcheck-links.py"))
    errors, unchecked, checked = [], 0, 0
    cache = {}
    sealed = set()
    if policy.get("sealed_manifests"):
        for rel in tracked(root):
            if Path(rel).name != "SHA256SUMS": continue
            for line in (root / rel).read_text(encoding="utf-8", errors="replace").splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2: sealed.add((root / rel).parent.joinpath(parts[1].strip().lstrip("*")).resolve())
    for rel in paths:
        if any(fnmatch.fnmatchcase(rel, pat) for pat in policy.get("exclude", [])):
            continue
        path = root / rel
        if path.resolve() in sealed or path.suffix.lower() in policy.get("generated_extensions", []): continue
        record_prefix = policy.get("record_prefix")
        if record_prefix and rel.startswith(record_prefix):
            if path.suffix.lower() not in set(policy.get("spdx_extensions", SPDX_EXT)): continue
            if re.search(policy.get("generated_page_pattern", r"(?!)"), rel): continue
        if not path.is_file() or path.suffix.lower() in set(policy.get("binary_extensions", BINARY)):
            continue
        data = path.read_bytes()
        if b"\0" in data:
            continue
        if b"\r" in data: errors.append(f"{rel}: CR line endings")
        if data and not data.endswith(b"\n"): errors.append(f"{rel}: missing final newline")
        text = data.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if line.rstrip(" \t") != line: errors.append(f"{rel}:{n}: trailing whitespace")
        spdx = path.suffix.lower() in set(policy.get("spdx_extensions", SPDX_EXT)) or Path(rel).parts[0] in policy.get("spdx_directories", [".githooks"])
        if spdx and path.name not in policy.get("spdx_exempt", ["CLAUDE.md"]) and not path.name.startswith("LICENSE"):
            if "SPDX-License-Identifier:" not in "\n".join(text.splitlines()[:8]):
                errors.append(f"{rel}: no SPDX header in first eight lines")
        if path.suffix.lower() != ".md": continue
        for target in parser["targets"](text):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I): continue
            file, _, anchor = target.partition("#")
            destination = (path.parent / unquote(file)).resolve() if file else path.resolve()
            # Unavailable sibling checkouts remain explicitly unverified.
            try: outside = not destination.is_relative_to(root)
            except ValueError: outside = True
            if outside:
                try: sibling = root.parent / destination.relative_to(root.parent).parts[0]
                except ValueError: sibling = None
                if sibling is None or not sibling.exists():
                    unchecked += 1
                    continue
            checked += 1
            if not destination.exists(): errors.append(f"{rel}: missing link {target}")
            elif anchor and destination.suffix.lower() == ".md":
                if destination not in cache: cache[destination] = parser["anchors"](destination)
                if unquote(anchor) not in cache[destination]: errors.append(f"{rel}: missing anchor {target}")
    return errors, checked, unchecked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--policy", type=Path)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8")) if args.policy else None
    errors, checked, unchecked = check(args.root, args.paths, policy)
    for error in errors: print(error)
    print(f"check_tree: {len(errors)} problem(s); {checked} links checked; {unchecked} unavailable-sibling links NOT checked")
    return int(bool(errors))
