# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Negative controls for release style configuration drift."""

import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_verible_style import TEMPLATE, main


class VeribleStyleTests(unittest.TestCase):
    def check_profile(self, text, rules=""):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            (repo / ".verible.format").write_text(text)
            (repo / ".rules.verible_lint").write_text(rules)
            with contextlib.redirect_stdout(io.StringIO()):
                return main([str(repo)])

    def test_matching_profile(self):
        self.assertEqual(self.check_profile(TEMPLATE.read_text()), 0)

    def test_changed_and_duplicate_flags_fail(self):
        source = TEMPLATE.read_text()
        self.assertEqual(self.check_profile(source.replace("limit=100", "limit=80")), 1)
        self.assertEqual(self.check_profile(source + "\n--column_limit=100\n"), 1)

    def test_unexplained_waiver_fails(self):
        self.assertEqual(self.check_profile(TEMPLATE.read_text(), "-parameter-name-style\n"), 1)


if __name__ == "__main__":
    unittest.main()
