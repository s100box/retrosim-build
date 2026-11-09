#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
import argparse
from pathlib import Path
from retrosim_build.coverage import merge

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary")
    parser.add_argument("--no-annotate", action="store_true")
    parser.add_argument("inputs", nargs="+")
    args = parser.parse_args()
    raise SystemExit(merge(args.inputs, args.output, cwd=Path.cwd(), summary=args.summary, annotate=not args.no_annotate))
