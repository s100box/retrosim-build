# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Exercise shared hook discovery with isolated toolchain pins."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class GateEnvironmentTests(unittest.TestCase):
    def test_live_overrides_and_stale_roots(self):
        pin = (ROOT / "toolchain.ninja").read_text()
        bash = (re.search(r"^bash_exe = (.+)$", pin, re.M).group(1)
                if os.name == "nt" else shutil.which("bash"))
        if not bash or not Path(bash).exists():
            self.skipTest("Bash unavailable")
        with tempfile.TemporaryDirectory(prefix="gate-env-") as directory:
            base = Path(directory)
            (base / "hooks").mkdir()
            shutil.copyfile(ROOT / "hooks/gate-env.sh", base / "hooks/gate-env.sh")
            pinned = base / "pinned tools"
            explicit = base / "explicit tools"
            pinned.mkdir()
            explicit.mkdir()
            (base / "toolchain.ninja").write_text(
                "\n".join(f"{name} = {pinned.as_posix()}" for name in
                          ("verible_root", "oss_cad_suite", "vs_root")) + "\n")
            for variable in ("VERIBLE_ROOT", "OSS_CAD_SUITE", "VS_ROOT"):
                for override, expected in ((explicit, explicit), (base / "missing", pinned)):
                    with self.subTest(variable=variable, override=override.name):
                        env = dict(os.environ)
                        env.pop("SKIP_GATE", None)
                        for name in ("VERIBLE_ROOT", "OSS_CAD_SUITE", "VS_ROOT"):
                            env.pop(name, None)
                        env[variable] = override.as_posix()
                        result = subprocess.run(
                            [bash, "-c", '. "$1"; printf "%s" "${!2}"',
                             "test", (base / "hooks/gate-env.sh").as_posix(), variable],
                            env=env, text=True, capture_output=True, check=True)
                        self.assertEqual(result.stdout, expected.as_posix())


if __name__ == "__main__":
    unittest.main()
