# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Numbered document citations with consumer-owned authority patterns."""
import argparse
import fnmatch
import json
from pathlib import Path
import re
import subprocess
from .tree import tracked

NUMBER = r"[0-9]+(?:\.[0-9]+)*"
HEADING = re.compile(r"^#{2,4} (" + NUMBER + r")\.? ")
SIGN = re.compile(r"§(" + NUMBER + r")")
JOIN = re.compile(r"\)?,? (?:and |or |to )?|-|–")


def headings(text):
    return {match[1] for line in text.splitlines() if (match := HEADING.match(line))}


def owned(line, policy):
    foreign = re.compile(policy["foreign"], re.I)
    by_plan = re.compile(policy["by_plan"], re.I) if policy.get("by_plan") else None
    by_board = re.compile(policy["by_board"], re.I) if policy.get("by_board") else None
    previous_end, previous = None, "own"
    for match in SIGN.finditer(line):
        if previous_end is not None and JOIN.fullmatch(line[previous_end:match.start()]):
            owner = previous
        else:
            before = line[:match.start()][-60:]
            owner = ("board" if by_board and by_board.search(before) else
                     None if foreign.search(before) else
                     "plan" if by_plan and by_plan.search(before) else "own")
        if owner is not None: yield match[1], owner
        previous_end, previous = match.end(), owner


def check(root, policy, exclude=()):
    if policy.get("mode") == "qualified": return qualified_check(root, policy, exclude)
    root = Path(root).resolve()
    plan = headings((root / policy["plan"]).read_text(encoding="utf-8"))
    board = headings((root / policy["board"]).read_text(encoding="utf-8")) if policy.get("board") else set()
    for section in policy.get("required_sections", []):
        if section not in plan: raise ValueError("heading parser lost required section " + section)
    for probe in policy.get("probes", []):
        actual = [s for s, owner in owned(probe[0], policy) if owner != "board"]
        if actual != probe[1]: raise ValueError(f"citation policy fails probe {probe[0]!r}: {actual}")
    errors, count = [], 0
    for rel in tracked(root):
        if rel in exclude or any(fnmatch.fnmatchcase(rel, pat) for pat in policy.get("exclude", [])): continue
        try: text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeError, OSError): continue
        own = plan
        if any(fnmatch.fnmatchcase(rel, pattern) for pattern in policy.get("self_documents", [])) and rel != policy["plan"]:
            own = headings(text)
        if any(rel.startswith(prefix) for prefix in policy.get("board_directories", [])): own = board
        for n, line in enumerate(text.split("\n"), 1):
            for section, owner in owned(line, policy):
                count += 1
                authority = plan if owner == "plan" else board if owner == "board" else own
                if section not in authority: errors.append(f"{rel}:{n}: missing {owner} section {section}")
    return errors, count


def qualified_check(root, policy, exclude=()):
    """Multiple authorities with forward/reverse qualifiers and bare citations.

    Policy preserves the consumer's attribution and population rules, including
    duplicate checks where a qualified reference is also an owned bare one.
    """
    root = Path(root).resolve()
    documents = policy["documents"]
    sets, texts = {}, {}
    for name, rel in documents.items():
        texts[name] = (root / rel).read_text(encoding="utf-8")
        sets[name] = headings(texts[name])
        for value in policy.get("required", {}).get(name, []):
            if value not in sets[name]: raise ValueError("missing authority heading " + name + ":" + value)
        for value in policy.get("forbidden", {}).get(name, []):
            if value in sets[name]: raise ValueError("invented authority heading " + name + ":" + value)
    patterns = {name: re.compile(value) for name, value in policy["patterns"].items()}
    errors, count = [], 0
    def report(rel, line, section, name):
        nonlocal count
        count += 1
        if section not in sets[name]: errors.append(f"{rel}:{line}: missing {name} section {section}")
    def tail(match): return re.search("(" + NUMBER + r")$", match[0])[1]
    for rule in policy["document_rules"]:
        name, other = rule["own"], rule["other"]
        for n, line in enumerate(texts[name].split("\n"), 1):
            owned_numbers = set()
            for match in patterns[rule["other_pattern"]].finditer(line):
                section = tail(match); owned_numbers.add(section)
                report(documents[name], n, section, other)
            for match in SIGN.finditer(line):
                if match[1] in owned_numbers: continue
                owner = other if rule.get("line_other") and re.search(rule["line_other"], line) else name
                report(documents[name], n, match[1], owner)
    candidates = tracked(root)
    if policy.get("candidate_literals"):
        command = ["git", "-C", str(root), "grep", "-IlzF"]
        for literal in policy["candidate_literals"]: command += ["-e", literal]
        result = subprocess.run([*command, "--", "."], capture_output=True)
        if result.returncode not in (0, 1):
            raise ValueError("citation candidate scan failed: " + result.stderr.decode("utf-8", "replace"))
        candidates = result.stdout.decode("utf-8").split("\0")[:-1]
    files = [rel for rel in candidates if rel not in documents.values() and rel not in exclude]
    files += [rel for rel in policy.get("optional_files", []) if (root / rel).is_file()]
    for rel in files:
        if any(fnmatch.fnmatchcase(rel, pat) for pat in policy.get("exclude", [])): continue
        try: text = (root / rel).read_text(encoding="utf-8")
        except (UnicodeError, OSError): continue
        if "\0" in text: continue
        for n, line in enumerate(text.split("\n"), 1):
            qualified_bare_owner = set()
            for rule in policy["qualified_rules"]:
                for match in patterns[rule["pattern"]].finditer(line):
                    section = SIGN.match(match[0])[1] if rule.get("reverse") else tail(match)
                    report(rel, n, section, rule["owner"])
                    if rule.get("owns_bare"): qualified_bare_owner.add(section)
            if not any(fnmatch.fnmatchcase(rel, pat) for pat in policy.get("no_bare", [])):
                for match in SIGN.finditer(line):
                    if match[1] not in qualified_bare_owner: report(rel, n, match[1], policy["bare_owner"])
    return errors, count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("policy", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    excluded = [*args.exclude, str(args.policy.resolve().relative_to(args.root.resolve())).replace("\\", "/")]
    errors, count = check(args.root, policy, excluded)
    for error in errors: print(error)
    print(f"doc_refs: {count} citations checked; {len(errors)} problem(s)")
    return int(bool(errors))
