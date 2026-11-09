# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from retrosim_build.toolchain import Toolchain, read_pins
from retrosim_build.process import run
from retrosim_build.manifest import arguments
from retrosim_build.consumer import audit


class HostServicesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="retrosim host ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_toolchain_expansion_and_overrides(self):
        root = self.root
        (root / "live").mkdir()
        (root / "override").mkdir()
        pin = root / "toolchain.ninja"
        pin.write_text(f"vs_root = {root.as_posix()}/live\nexe = $vs_root/tool\nliteral = $$name\n")
        self.assertEqual(read_pins(pin)["exe"], (root / "live/tool").as_posix())
        self.assertEqual(read_pins(pin)["literal"], "$name")
        tc = Toolchain(pin, {"VS_ROOT": str(root / "missing")})
        self.assertEqual(tc.resolve("VS_ROOT").source, "pin:vs_root")
        tc = Toolchain(pin, {"VS_ROOT": str(root / "override")})
        self.assertEqual(tc.resolve("VS_ROOT").source, "environment:VS_ROOT")
        pin.write_text("a = $b\nb = $a\n")
        with self.assertRaises(ValueError):
            read_pins(pin)

    def test_manifest_quoting_and_flags(self):
        manifest = self.root / "test.f"
        manifest.write_text('# comment\n-g2012\n-I "include dir"\n-DNAME=3\n"source file.sv" # note\n')
        result = arguments(manifest, self.root)
        self.assertEqual(result, ["-g2012", "-I" + str(self.root / "include dir"), "-DNAME=3", str(self.root / "source file.sv")])
        self.assertNotIn("-g2012", arguments(manifest, self.root, verilator=True))

    def test_exit_status_verdict_timeout_and_fresh_log(self):
        log = self.root / "test.log"
        log.write_text("PASS\n")
        result = run([sys.executable, "-c", "print('PASS'); raise SystemExit(7)"], cwd=self.root, log=log)
        self.assertFalse(result.passed("^PASS"))
        self.assertIn("PROCESS EXIT: 7", log.read_text(encoding="utf-8"))
        result = run([sys.executable, "-c", "print('unrelated')"], cwd=self.root, log=log)
        self.assertFalse(result.passed("^PASS"))
        result = run([sys.executable, "-c", "import time; time.sleep(30)"], cwd=self.root, log=log, timeout=.1)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.returncode, 124)

    def test_consumer_checker_and_policy(self):
        root = self.root
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".githooks").mkdir()
        (root / ".githooks/pre-commit").write_text("#!/bin/sh\nexit 0\n")
        (root / "build.ninja").write_text('bash = C:/PROGRA~1/Git/bin/bash.exe\n')
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        self.assertEqual({x["rule"] for x in audit(root)}, {"windows-bash", "hook-environment"})
        (root / ".retrosim-tooling.json").write_text(json.dumps({"exceptions": [{"path": ".githooks/*", "rule": "hook-environment", "reason": "fixture hook"}]}))
        self.assertEqual({x["rule"] for x in audit(root)}, {"windows-bash"})
        (root / "build.ninja").write_text('bash = bash\nrule lint\n  command = $bash lint.sh\n')
        self.assertEqual(audit(root), [])


if __name__ == "__main__":
    unittest.main()
