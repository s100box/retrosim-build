# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Checks for RTL names used to validate timing-constraint scope."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import sdc_coverage


class RtlNames(unittest.TestCase):
    def test_generate_scopes_and_instances(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "top.sv").write_text(
                "module top;\n"
                "// begin : comment_scope\n"
                "if (1) begin : lanes\n"
                "  cell plain_inst ();\n"
                "  cell #(.WIDTH(8)\n"
                "  ) param_inst ();\n"
                "end\nendmodule\n", encoding="utf-8",
            )
            names, _, count = sdc_coverage.rtl_names([temp])
            self.assertEqual(count, 1)
            self.assertTrue({"lanes", "plain_inst", "param_inst"} <= names)
            self.assertNotIn("comment_scope", names)

    def test_begin_requires_a_word_boundary(self):
        self.assertEqual(sdc_coverage.RE_GEN.findall("begin : valid"), ["valid"])
        self.assertEqual(sdc_coverage.RE_GEN.findall("notbegin : invalid"), [])
