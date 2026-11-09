#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Content identity for explicitly declared IP-cache dependencies and settings."""
import argparse
import hashlib
import json
from pathlib import Path


def file_key(inputs, settings=()):
    files = {}
    for value in inputs:
        path = Path(value).resolve(strict=True)
        files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps({"files": files, "settings": list(settings)}, sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--setting", action="append", default=[])
    args = parser.parse_args()
    print(file_key(args.input, args.setting))
