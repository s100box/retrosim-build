#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Check consumer formatter settings and inventory justified local lint exceptions.

This compares configuration, not RTL conformance. Run each consumer's lint and
simulation gates as well. Missing Verible profiles fail unless explicitly allowed.
"""

import argparse
from pathlib import Path


TEMPLATE = Path(__file__).resolve().parents[1] / "templates/verible.format"


def formatter_settings(path):
    """Parse flag values, rejecting duplicate or malformed settings."""
    flags = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = line.split("#", 1)[0].strip()
        if not value:
            continue
        if not value.startswith("--") or "=" not in value:
            raise ValueError(f"{path}:{number}: expected --flag=value")
        key, value = value.split("=", 1)
        if key in flags:
            raise ValueError(f"{path}:{number}: duplicate {key}")
        flags[key] = value
    return flags


def lint_exceptions(path):
    """Return local settings, requiring a preceding reason comment for each."""
    entries, comments = [], []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            comments.append(stripped[1:].strip())
        elif stripped:
            if not comments or not any(comments):
                raise ValueError(f"{path}:{number}: lint exception needs a reason comment")
            entries.append(stripped)
            comments = []
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", type=Path, nargs="+")
    parser.add_argument("--allow-unconfigured", action="store_true",
                        help="report repositories with no profile as unconfigured, not failures")
    args = parser.parse_args(argv)
    expected = formatter_settings(TEMPLATE)
    failed = False
    for repo in args.repositories:
        profile, rules = repo / ".verible.format", repo / ".rules.verible_lint"
        if not profile.exists() and not rules.exists():
            print(f"{repo.name}: UNCONFIGURED (no Verible gate implied)")
            failed |= not args.allow_unconfigured
            continue
        try:
            actual = formatter_settings(profile)
            if actual != expected:
                changed = sorted(key for key in actual.keys() | expected.keys()
                                 if actual.get(key) != expected.get(key))
                raise ValueError(f"{repo}: formatter differs from shared profile: {', '.join(changed)}")
            entries = lint_exceptions(rules)
            print(f"{repo.name}: PASS; lint exceptions: {', '.join(entries) or 'none (defaults)'}")
        except (OSError, ValueError) as error:
            print(f"FAIL: {error}")
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
