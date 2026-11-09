# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
from retrosim_build import bench, coverage
from retrosim_build.citations import check as check_citations, owned
from retrosim_build.process import Result
from retrosim_build.program import preflight
from retrosim_build.toolchain import Toolchain, Selection
from retrosim_build.tree import check as check_tree
import build_key


class SharedValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="shared services ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def fixture(self):
        root = self.root
        (root / "benches").mkdir()
        (root / "source file.sv").write_text("module fixture; endmodule\n")
        (root / "benches/fixture.f").write_text('"source file.sv"\n')
        config = root / "suite.json"
        config.write_text(json.dumps({"root": ".", "manifests": "benches/*.f", "pass_pattern": "^fixture: PASS"}))
        return config

    def test_suite_status_marker_cache_and_empty_selection(self):
        config = self.fixture()
        output = self.root / "output"
        tc = unittest.mock.Mock()
        tc.resolve.return_value = Selection(sys.executable, "fixture")
        tc.environment.return_value = dict(os.environ)
        def successful(argv, *, cwd, log, **kwargs):
            Path(log).parent.mkdir(parents=True, exist_ok=True)
            Path(log).write_text("fixture: PASS\n")
            return Result(0, False, Path(log))
        with patch.object(bench, "Toolchain", return_value=tc), patch.object(bench, "run", side_effect=successful):
            self.assertEqual(bench.execute(config, mode="compile", output=output), 0)
            self.assertEqual(bench.execute(config, mode="run", output=output), 0)
            (self.root / "source file.sv").write_text("module changed; endmodule\n")
            with self.assertRaisesRegex(ValueError, "stale"):
                bench.execute(config, mode="run", output=output)
            with self.assertRaisesRegex(ValueError, "no bench"):
                bench.execute(config, selected="absent", output=output)
            with self.assertRaisesRegex(ValueError, "resource"):
                bench.execute(config, jobs=100, output=output)
        def false_pass(argv, *, cwd, log, **kwargs):
            result = successful(argv, cwd=cwd, log=log)
            if Path(log).name == "run.log": result.returncode = 7
            return result
        with patch.object(bench, "Toolchain", return_value=tc), patch.object(bench, "run", side_effect=false_pass):
            self.assertEqual(bench.execute(config, output=output), 1)

    def test_merge_uses_only_explicit_data_and_propagates_failure(self):
        current = self.root / "current.dat"; current.write_text("current")
        old = self.root / "old.dat"; old.write_text("stale")
        seen = []
        tc = unittest.mock.Mock()
        tc.resolve.return_value = Selection(sys.executable, "fixture")
        tc.environment.return_value = dict(os.environ)
        annotation = self.root / "annotate"
        annotation.mkdir()
        (annotation / "old-source.v").write_text("stale annotation")
        def execute(argv, *, log, **kwargs):
            seen.append(argv)
            Path(log).write_text("log")
            if "--write" in argv: Path(argv[2]).write_text("merged")
            return Result(0, False, Path(log))
        with patch.object(coverage, "run", side_effect=execute):
            self.assertEqual(coverage.merge([current], self.root, cwd=self.root, tc=tc), 0)
        self.assertNotIn(str(old), seen[0])
        self.assertFalse((annotation / "old-source.v").exists())
        with self.assertRaises(ValueError):
            coverage.merge([], self.root, cwd=self.root, tc=tc)
        with self.assertRaises(ValueError):
            coverage.merge([current], self.root, cwd=self.root, tc=tc, groups={"bad": [old]})
        with patch.object(coverage, "run", return_value=Result(8, False, self.root / "log")):
            self.assertEqual(coverage.merge([current], self.root, cwd=self.root, tc=tc), 1)

    def test_snapshot_key_changes_with_inputs_settings_and_tools(self):
        root = self.root
        args = root / "args"; source = root / "top.sv"; tool = root / "tool"
        args.write_text(str(source)); source.write_text("first"); tool.write_text("compiler one")
        (root / "CMakeLists.txt").write_text("cmake")
        original = build_key.key(root, args, ["mode=vl"], [tool])
        self.assertEqual(original, build_key.key(root, args, ["mode=vl"], [tool]))
        self.assertNotEqual(original, build_key.key(root, args, ["mode=cov"], [tool]))
        self.assertNotEqual(build_key.key(root, args, [], [tool], environ={}),
                            build_key.key(root, args, [], [tool], environ={'CXXFLAGS':'-DCHANGED'}))
        tool.write_text("compiler two")
        self.assertNotEqual(original, build_key.key(root, args, ["mode=vl"], [tool]))
        source.write_text("changed")
        self.assertNotEqual(original, build_key.key(root, args, ["mode=vl"], [tool]))

    def test_bench_receipt_includes_shared_native_builder(self):
        config = self.fixture()
        manifest = self.root / "benches/fixture.f"
        tool = Selection(sys.executable, "fixture")
        args = [str(self.root / "source file.sv")]
        original = bench.fingerprint(args, {}, tool, manifest, self.root)
        original_read = Path.read_bytes
        def changed(path):
            data = original_read(path)
            return data + b"\n# changed policy\n" if path == TOOLS / "verilator.cmake" else data
        with patch.object(Path, "read_bytes", changed):
            self.assertNotEqual(original, bench.fingerprint(args, {}, tool, manifest, self.root))

    def test_citation_policy_is_utf8_with_legacy_windows_locale(self):
        root = self.root
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "plan.md").write_text("## 1. Scope\n", encoding="utf-8")
        (root / "note.md").write_text("plan §1\n", encoding="utf-8")
        policy = {"mode":"qualified", "documents":{"plan":"plan.md"},
                  "document_rules":[], "patterns":{"plan":"plan §[0-9]+"},
                  "qualified_rules":[{"pattern":"plan", "owner":"plan"}],
                  "bare_owner":"plan", "no_bare":["*"], "candidate_literals":["§"]}
        path = root / "policy.json"
        path.write_text(json.dumps(policy, ensure_ascii=False), encoding="utf-8")
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        result = subprocess.run([sys.executable,"-X","utf8=0",str(TOOLS / "check_citations.py"),str(path),"--root",str(root)],
                                capture_output=True, env={**os.environ,"PYTHONIOENCODING":"utf-8"})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(b"1 citations checked", result.stdout)

    def test_programming_preflight_is_closed_on_missing_stale_or_bad_timing(self):
        root = self.root
        source = root / "source.sv"; source.write_text("source")
        sdc = root / "board.sdc"; sdc.write_text("constraints")
        artifact = root / "image.fs"; artifact.write_text("bitstream")
        report = root / "timing.html"; report.write_text("report")
        self.assertEqual(preflight(artifact, report, sdc, [source], timing=lambda _: 0), artifact)
        with self.assertRaisesRegex(ValueError, "timing"):
            preflight(artifact, report, sdc, [source], timing=lambda _: 1)
        os.utime(source, ns=(artifact.stat().st_mtime_ns + 1000000000,) * 2)
        with self.assertRaisesRegex(ValueError, "stale"):
            preflight(artifact, report, sdc, [source], timing=lambda _: 0)
        with self.assertRaises(FileNotFoundError):
            preflight(root / "missing.fs", report, sdc, [source])

    def test_programmer_arguments_and_modes(self):
        artifact = self.root / "image with spaces.fs"; artifact.write_text("image")
        bash = Toolchain().resolve("BASH_EXE").path
        code = '''set -e
. "$1/gowin.sh"
record() { printf '<%s>' "$@"; printf '\\n'; }
PROG=record
gowin_board nano20k
_gowin_program_artifact "$2" sram --device "$GOWIN_DEVICE" --cable 'a cable with spaces'
_gowin_program_artifact "$2" flash --device "$GOWIN_DEVICE"
'''
        result = subprocess.run([bash, "-c", code, "test", str(TOOLS.parent), artifact.as_posix()],
                                capture_output=True, text=True, check=True)
        self.assertIn('<--cable><a cable with spaces>', result.stdout)
        self.assertIn('<--run><24>', result.stdout)
        self.assertIn('<--run><2>', result.stdout)
        self.assertIn('<--run><8>', result.stdout)
        self.assertNotIn('<--run><6>', result.stdout)

    def test_hygiene_and_sealed_evidence(self):
        root = self.root
        sealed = root / "sealed.md"; sealed.write_bytes(b"not an authored page\r\n")
        (root / "SHA256SUMS").write_text(hashlib.sha256(sealed.read_bytes()).hexdigest() + ' *sealed.md\n', newline='\n')
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        errors, _, _ = check_tree(root, policy={"sealed_manifests": True})
        self.assertEqual(errors, [])
        errors, _, _ = check_tree(root)
        self.assertTrue(any("CR line" in error for error in errors))

    def test_citation_authority_and_negative_control(self):
        root = self.root
        (root / "plan.md").write_text("## 1. Main\n### 1.2. Detail\n")
        (root / "code.py").write_text("# plan §1.2; foreign guide §99\n", encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        policy = {"plan": "plan.md", "foreign": r"guide\s*$", "required_sections": ["1.2"]}
        self.assertEqual(check_citations(root, policy)[0], [])
        (root / "code.py").write_text("# plan §88\n", encoding="utf-8")
        self.assertTrue(check_citations(root, policy)[0])
