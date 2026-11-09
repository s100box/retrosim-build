#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Print a resolved tool path or its provenance as JSON."""
import argparse
import json
from retrosim_build.toolchain import Toolchain

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    selection = Toolchain().resolve(args.name)
    print(json.dumps(selection.provenance()) if args.json else selection.path)
