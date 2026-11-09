# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Reject errors, empty models and stale traces as formal evidence."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import formal_suite


class FormalSuiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="formal suite ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "test.sby").write_text("[options]\nmode prove\n")

    def evaluate(self, status="PASS", code=0, cells=1, trace=False,
                 timeout=False, expected="PASS"):
        def fake_run(command, **kwargs):
            work = Path(command[3])
            (work / "model").mkdir()
            (work / "model/design_prep.il").write_text("  cell $assert property\n" * cells)
            (work / "status").write_text(status + "\n")
            if trace:
                (work / "engine_0").mkdir()
                (work / "engine_0/trace.vcd").write_text("counterexample")
            return SimpleNamespace(timed_out=timeout, returncode=code)

        job = dict(name="test", file="test.sby", expect=expected)
        with patch.object(formal_suite.shutil, "which", return_value="sby"), \
                patch.object(formal_suite, "run", side_effect=fake_run):
            return formal_suite.run_job(job, self.root, self.root, {"PATH": ""})[1]

    def test_positive_requires_nonempty_success(self):
        self.assertTrue(self.evaluate()["pass"])
        self.assertFalse(self.evaluate(cells=0)["pass"])
        self.assertFalse(self.evaluate(code=1)["pass"])
        self.assertFalse(self.evaluate(timeout=True)["pass"])

    def test_negative_requires_trace_and_expected_exit(self):
        self.assertTrue(self.evaluate("FAIL", 2, trace=True, expected="FAIL")["pass"])
        self.assertFalse(self.evaluate("FAIL", 2, expected="FAIL")["pass"])
        self.assertFalse(self.evaluate("ERROR", 16, trace=True, expected="FAIL")["pass"])
        self.assertFalse(self.evaluate("UNKNOWN", 4, trace=True, expected="FAIL")["pass"])

    def test_work_directories_do_not_reuse_stale_evidence(self):
        first = self.evaluate("FAIL", 2, trace=True, expected="FAIL")
        second = self.evaluate("FAIL", 2, expected="FAIL")
        self.assertNotEqual(first["work"], second["work"])
        self.assertFalse(second["pass"])


if __name__ == "__main__":
    unittest.main()
