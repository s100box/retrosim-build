#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
import argparse
import re
from retrosim_build.process import run
from retrosim_build.toolchain import Toolchain

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a consumer command with a fresh log, timeout and explicit verdicts")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--pass-pattern", required=True)
    parser.add_argument("--fail-pattern")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command: parser.error("a command is required after --")
    result = run(command, cwd=args.cwd, log=args.log, timeout=args.timeout, env=Toolchain().environment())
    text = result.log.read_text(encoding="utf-8", errors="replace")
    print(text, end="")
    passed = result.passed(args.pass_pattern) and not (args.fail_pattern and re.search(args.fail_pattern, text, re.M))
    raise SystemExit(0 if passed else 1)
