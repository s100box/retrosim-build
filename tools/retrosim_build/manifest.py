# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""One argument per line RTL manifests, relative to an explicit source root."""
from pathlib import Path
import shlex


def arguments(path, root, *, verilator=False):
    root = Path(root)
    result = []
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        lexer = shlex.shlex(line, posix=True)
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
        if not tokens:
            continue
        # Preserve an unquoted source path containing spaces as one line item.
        if not tokens[0].startswith("-"):
            value = " ".join(tokens)
            result.append(str((root / value).resolve()))
            continue
        if len(tokens) == 2 and tokens[0] in ("-I", "-f", "-F"):
            tokens = [tokens[0] + tokens[1]]
        for value in tokens:
            if value.startswith("-g") and verilator:
                continue
            if value.startswith(("-I", "-f", "-F")) and len(value) > 2:
                value = value[:2] + str((root / value[2:]).resolve())
            result.append(value)
    return result
