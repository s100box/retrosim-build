# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Check consumer build metadata without opening RTL or vendored sources."""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess
from .toolchain import ROOT

SKIP = {"vendor", "third_party", "third-party", "external", "refs", "roms", "target", "disasm", "oskit"}
PIN = re.compile(r"(?:C:[/\\](?:Gowin[/\\]Gowin_V\d|Users[/\\][^/\\]+[/\\](?:verible|oss-cad-suite))|Microsoft Visual Studio[/\\](?:18|2022)[/\\])")


def audit(root):
    root = Path(root).resolve()
    policy_path = root / ".retrosim-tooling.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8")) if policy_path.exists() else {}
    exceptions = policy.get("exceptions", [])
    for item in exceptions:
        if not item.get("reason") or not item.get("path") or not item.get("rule"):
            raise ValueError("tooling exceptions require path, rule, and reason")
    files = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"], text=True).split("\0")[:-1]
    issues = []
    def finding(path, line, rule, message):
        if any(item["rule"] == rule and fnmatch.fnmatchcase(path, item["path"]) for item in exceptions):
            return
        issues.append({"path": path, "line": line, "rule": rule, "message": message})
    for rel in files:
        path = Path(rel)
        if SKIP.intersection(path.parts) or not (path.suffix in (".ps1", ".sh", ".ninja", ".tcl") or rel.startswith(".githooks/")):
            continue
        if not (root / rel).is_file():
            continue
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(("#", "//")):
                continue
            if PIN.search(line):
                finding(rel, n, "local-pin", "use the shared toolchain pin or an explicit environment override")
            for reference in re.findall(r"retrosim-build[/\\]([\w./\\-]+\.(?:py|sh|ps1|tcl|ninja))", line):
                reference = reference.replace("\\", "/")
                if not (ROOT / reference).is_file():
                    finding(rel, n, "missing-shared-path", "missing shared helper: " + reference)
            # A literal command, not $bash. POSIX build.ninja entry points
            # deliberately select bash through a variable; Windows wrappers
            # must source the shared pin rather than use a short local path.
            if path.suffix == ".ninja" and re.search(r"^\s*(?:command\s*=.*(?<![\w/$])bash\s|bash\s*=\s*C:)", line):
                finding(rel, n, "windows-bash", "select the shared quoted $bash_exe for Windows Ninja")
        if rel in (".githooks/pre-commit", ".githooks/pre-push") and "gate-env.sh" not in text:
            finding(rel, 1, "hook-environment", "bootstrap shared gate-env.sh, or document the deliberate exception")
    return issues


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repositories", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    results = {str(root): audit(root) for root in args.repositories}
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for root, issues in results.items():
            for issue in issues:
                print(f"{root}/{issue['path']}:{issue['line']}: {issue['rule']}: {issue['message']}")
        print(f"consumer audit: {sum(map(len, results.values()))} finding(s), {len(results)} repository/repositories")
    return int(any(results.values()))
