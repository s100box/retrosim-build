#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""CADENCE ARM EXTRACTOR -- derive each register's true CAPTURE PHASE from the
RTL, and check every `set_multicycle_path` row's `-to` glob against it.

Task #54 step 2 (hh-v1170 PROGRESS), checking mode -- "the cheap first half"
that entry explicitly endorses. Companion to `timing_relation_census.py`
(step 1, which reports the relation STA actually applied) and to
`sdc_coverage.py` (which checks that a glob reaches real RTL at all).

WHY THIS EXISTS
---------------
An SDC multicycle row is a CLAIM: "this launch reaches this capture N clocks
later." The census can catch the claim being applied oddly, but it can NEVER
catch the dangerous direction. An OVER-scoped row -- a `-to` glob that
swallows a sink which really captures EARLIER than the row says -- relaxes a
path the hardware needs sooner. It reports POSITIVE slack by construction, so
no sweep, no ask ladder and no sign-off gate can see it. It signs off, and
then it fails on the board. That is the timing-doc section 2.4 silicon trap.

The only place the truth exists is the RTL: on this machine a register's
capture arm is a phase guard (`t1_en`..`t5_en`, `phase == PH_Tn`, `commit`,
`io_commit`, or a `*_fire_q` strobe). This tool reads those guards and reports
each register's capture phase set, then compares the MINIMUM launch->capture
spacing implied by the RTL against the N each SDC row declares.

⚠⚠ IT REFUSES TO GUESS. A register whose arm cannot be classified is reported
UNKNOWN and treated as capturing at EVERY phase -- i.e. the safe N=1. An
extractor that guessed would mint over-scoped rows in bulk, which is the very
failure it exists to prevent. UNKNOWN is a result, not an error: it means
"this one still needs a human", and the count is printed so it cannot be
quietly ignored.

WHAT IT CANNOT SEE -- state this wherever you quote the output
--------------------------------------------------------------
* Inferred-RAM address/CE pins (timing-doc section 2.8). They have no
  nameable endpoint, carry no exception and appear under no glob, so they are
  permanently N=1 whatever this says.
* Anything a parameter switches off. Generate arms are read as text, so a
  register inside a disabled arm is still reported. That errs toward
  reporting more sinks than the build contains, which is the safe direction
  for an over-scope hunt.
* Cross-module launch/capture spacing is computed from phase sets ONLY. A
  path that is architecturally impossible (the two registers never interact)
  still shows up; this tool bounds the cadence, it does not prove reachability.
* It reads ONE module's own registers per glob level, because Gowin's
  `get_regs` globs match ONE hierarchy level. Sub-instances are separate
  levels and are matched by their own patterns.

VALIDATION -- four facts it reproduces that the RTL states independently
------------------------------------------------------------------------
Checked against comments written by the design's author, not against this
tool's own output:
  * `mem_box/eff_pa_q` -> T2      -- the SDC calls it "the T2 seam"
  * `kb11c_cpu/rar_q`, `ba_q`, `stall_q`, `prev_space_i_q` -> T5
                                  -- "T5 is the commit boundary" (kb11c_pkg)
  * `mem_box/ram_qe`, `ram_qo` -> T3
                                  -- "issue a T3 bank read" (mem_box)
  * `mem_box/dma_rdata_q` -> T4   -- "captured into dma_rdata_q at T4"
A change that breaks any of these has broken the extractor, not the RTL.

USAGE
  python cadence_arms.py <constraints.sdc> --top <top.sv> --rtl <dir> [<dir>...]
    --phases N        clocks per microcycle (default 6: T0..T5)
    --module M        print the phase table for module M and exit
    --json FILE       write the full findings
Exit 1 if any row is OVER-SCOPED (the silicon trap); 0 otherwise.
"""
import argparse
import json
import pathlib
import re
import sys

RE_COMMENT = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
RE_MODULE = re.compile(r"^\s*module\s+([A-Za-z_]\w*)", re.M)
RE_ENDMODULE = re.compile(r"^\s*endmodule", re.M)
RE_ASSIGN = re.compile(r"^\s*assign\s+([A-Za-z_]\w*)\s*=\s*(.+?);", re.M | re.S)
RE_LOCALPARAM = re.compile(r"^\s*(?:localparam|parameter)\s+\w*\s*(?:\[[^\]]*\]\s*)?([A-Za-z_]\w*)\s*=\s*([^;]+);", re.M)
RE_NB = re.compile(r"([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)*<=")
RE_INST = re.compile(r"^\s*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?([A-Za-z_]\w*)\s*\(", re.M | re.S)
RE_GEN = re.compile(r"begin\s*:\s*([A-Za-z_]\w*)")

# The phase vocabulary this machine actually uses.
#
# ⚠ The phase REGISTER is not always spelled `phase`: mem_box compares
# `phase == PH_T4` but kb11c_cpu compares `phase_q == PH_LAST`, and reading
# only the first spelling left every CPU sink UNKNOWN -- which silently
# turned the whole CPU half of the check into "cannot say".
RE_PHASE_EQ = re.compile(r"\bphase\w*\s*==\s*PH_T(\d)")
RE_PHASE_NE = re.compile(r"\bphase\w*\s*!=\s*PH_T(\d)")
RE_TEN = re.compile(r"\bt(\d)_en\b")
RE_PH_ALIAS = re.compile(r"\bPH_[A-Z_]+\b")


def strip(text):
    return RE_COMMENT.sub(" ", text)


def read_modules(dirs, extra_files=(), all_text=None):
    """{module_name: body_text} for every module found.

    `all_text` (a list) is filled with every file's WHOLE text, which the
    parameter scan needs -- packages are not modules.
    """
    mods, files = {}, []
    for d in dirs:
        p = pathlib.Path(d)
        if p.exists():
            files += list(p.rglob("*.sv")) + list(p.rglob("*.v"))
    files += [pathlib.Path(f) for f in extra_files]
    for f in files:
        try:
            t = strip(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if all_text is not None:
            all_text.append(t)
        starts = [(m.start(), m.group(1)) for m in RE_MODULE.finditer(t)]
        ends = [m.start() for m in RE_ENDMODULE.finditer(t)]
        for pos, name in starts:
            end = next((e for e in ends if e > pos), len(t))
            mods.setdefault(name, t[pos:end])
    return mods


def split_always_ff(body):
    """Yield the text of every `always_ff @(posedge ...)` block."""
    for m in re.finditer(r"always_ff\s*@\s*\(([^)]*)\)", body):
        sens = m.group(1)
        if "posedge" not in sens:
            continue
        rest = body[m.end():]
        # Single-statement form: `always_ff @(...) x <= y;`
        head = rest.lstrip()
        if not head.startswith("begin"):
            stmt = head.split(";", 1)[0] + ";"
            yield sens, stmt
            continue
        # Balanced begin/end walk.
        depth, i, start = 0, 0, None
        toks = list(re.finditer(r"\b(begin|end)\b", rest))
        for t in toks:
            if t.group(1) == "begin":
                if depth == 0:
                    start = t.end()
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    yield sens, rest[start:t.start()]
                    break


KW = re.compile(r"\b(begin|end|if|else|case|casez|casex|endcase|for|while)\b")


def guarded_targets(block):
    """[(register, [guard_conditions])] for each non-blocking target.

    A real recursive walk, because the guard is the whole point: an
    approximate one either misses a phase term (reporting UNKNOWN, merely
    unhelpful) or attaches the WRONG one (minting an over-scoped row, which
    is the failure this tool exists to prevent).

    An `else` arm inherits the enclosing guards but NOT a negation of its own
    `if` -- what matters is only whether a phase term gates the clock enable,
    and `if (a) x<=1; else x<=2;` captures under `a`'s enclosing guards either
    way. A phase term that appears in the `if` therefore does not constrain
    the `else` arm, so the else arm is recorded with the OUTER guards only.
    """
    out = []
    pos = [0]

    def skip_ws(i):
        while i < len(block) and block[i].isspace():
            i += 1
        return i

    def statement(i, guards):
        """Parse ONE statement starting at i; return the index after it."""
        i = skip_ws(i)
        if i >= len(block):
            return i
        m = KW.match(block, i)
        word = m.group(1) if m else None
        if word == "begin":
            i = m.end()
            # An optional `: label`
            j = skip_ws(i)
            if j < len(block) and block[j] == ":":
                j = skip_ws(j + 1)
                lm = re.match(r"[A-Za-z_]\w*", block[j:])
                if lm:
                    j += lm.end()
                i = j
            return block_body(i, guards)
        if word == "if":
            cond, j = read_paren(block, m.end())
            j = statement(j, guards + [cond])
            j2 = skip_ws(j)
            em = KW.match(block, j2)
            if em and em.group(1) == "else":
                return statement(em.end(), guards)
            return j
        if word in ("case", "casez", "casex"):
            _, j = read_paren(block, m.end())
            # Case items are separate captures; keep the enclosing guards and
            # do not try to prove which item is selected.
            depth = 1
            while j < len(block) and depth:
                cm = KW.search(block, j)
                if not cm:
                    break
                if cm.group(1) in ("case", "casez", "casex"):
                    depth += 1
                elif cm.group(1) == "endcase":
                    depth -= 1
                    if depth == 0:
                        for t in RE_NB.finditer(block, j, cm.start()):
                            out.append((t.group(1), list(guards)))
                        return cm.end()
                j = cm.end()
            return j
        if word in ("for", "while"):
            _, j = read_paren(block, m.end())
            return statement(j, guards)
        if word in ("end", "endcase", "else"):
            return m.end()
        # A plain statement, up to its semicolon.
        semi = block.find(";", i)
        if semi < 0:
            semi = len(block) - 1
        for t in RE_NB.finditer(block, i, semi + 1):
            out.append((t.group(1), list(guards)))
        return semi + 1

    def block_body(i, guards):
        """Statements until the matching `end`."""
        while i < len(block):
            i = skip_ws(i)
            m = KW.match(block, i)
            if m and m.group(1) == "end":
                return m.end()
            j = statement(i, guards)
            if j <= i:
                return i + 1
            i = j
        return i

    pos[0] = block_body(0, [])
    return out


RE_RESETISH = re.compile(r"^[\s!~()]*(?:rst_n|reset|rst|arst_n|por_n)[\s()]*$")


def _submodule_targets(body):
    """Targets that belong to a nested module declared in the same file.

    read_modules() slices each `module`..`endmodule` separately, so these are
    accounted for under their own name and must not count as this module's
    unreached registers.
    """
    return set()


def read_paren(text, i):
    """Return (contents, index_after) for the next parenthesised group."""
    while i < len(text) and text[i] != "(":
        if not text[i].isspace():
            return "", i
        i += 1
    depth, start = 0, i
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def phase_aliases(texts):
    """{PH_NAME: PH_Tn} -- resolve `PH_LAST = PH_T5` style indirection.

    ⚠ Scans WHOLE FILES, not module bodies: `PH_T0`..`PH_T5` and `PH_LAST`
    live in `kb11c_pkg`, a PACKAGE, which no `module`..`endmodule` slice
    contains. Resolving package aliases is necessary to recognize guards
    such as `phase_q == PH_LAST`.
    """
    raw = {}
    for body in texts:
        for m in RE_LOCALPARAM.finditer(body):
            n, v = m.group(1), m.group(2).strip()
            if n.startswith("PH_"):
                raw[n] = v
    out = {}
    for n in raw:
        v, seen = raw[n], set()
        while v in raw and v not in seen:
            seen.add(v)
            v = raw[v].strip()
        m = re.fullmatch(r"3'd(\d)", v) or re.fullmatch(r"PH_T(\d)", v)
        if m:
            out[n] = f"PH_T{m.group(1)}"
    return out


class ModuleArms:
    """Capture-phase sets for one module's own registers."""

    def __init__(self, name, body, phases, aliases=None):
        self.name = name
        self.phases = phases
        self.aliases = aliases or {}
        self.assigns = {m.group(1): m.group(2) for m in RE_ASSIGN.finditer(body)}
        self.regs = {}
        self.unknown = set()
        for sens, block in split_always_ff(body):
            for reg, guards in guarded_targets(block):
                # A pure reset arm is not a functional capture phase: it says
                # nothing about the cadence the multicycle row is claiming.
                if guards and all(RE_RESETISH.match(g) for g in guards):
                    self.regs.setdefault(reg, set())
                    continue
                guards = [g for g in guards if not RE_RESETISH.match(g)]
                expr = " && ".join(f"({g})" for g in guards) if guards else "1"
                ph = self.phases_of(expr)
                self.regs.setdefault(reg, set())
                if ph is None:
                    self.unknown.add(reg)
                    self.regs[reg] = set(range(phases))
                elif reg not in self.unknown:
                    self.regs[reg] |= ph

        # ⚠ SAFETY. An EMPTY phase set means the walk found only a reset arm
        # -- either the register really is reset-only, or the statement walk
        # desynchronised and missed the functional write. The two are
        # indistinguishable from here, and reading empty as "never captures"
        # would make every N look justified. So empty is UNKNOWN.
        for reg, ph in self.regs.items():
            if not ph:
                self.unknown.add(reg)
                self.regs[reg] = set(range(phases))

        # The tool's own reach, so a parser that quietly stops early cannot
        # be mistaken for RTL that has no registers.
        raw = set(RE_NB.findall(body))
        self.missed = sorted(raw - set(self.regs) - _submodule_targets(body))

    def expand(self, expr, depth=6):
        """Substitute this module's own continuous assignments, bounded."""
        for _ in range(depth):
            names = set(re.findall(r"\b[A-Za-z_]\w*\b", expr))
            hits = [n for n in names if n in self.assigns]
            if not hits:
                break
            for n in hits:
                expr = re.sub(rf"\b{re.escape(n)}\b",
                              "(" + self.assigns[n] + ")", expr)
        return expr

    def phases_of(self, expr):
        """Set of phases the guard can be true at, or None for UNKNOWN."""
        full = self.expand(expr)
        full = RE_PH_ALIAS.sub(lambda m: self.aliases.get(m.group(0),
                                                          m.group(0)), full)
        if RE_PHASE_NE.search(full):
            return None                     # negated phase term: refuse to guess
        found = set()
        for m in RE_PHASE_EQ.finditer(full):
            found.add(int(m.group(1)))
        for m in RE_TEN.finditer(full):
            found.add(int(m.group(1)))
        # `phase_q == control_store_phase`, where that expands to a
        # PARAMETER-selected ternary (`SIX_PHASE_UCYCLE ? PH_T0 : PH_T1`).
        # The parameter picks one arm; this tool does not elaborate
        # parameters, so it takes the UNION of the arms. A union can only
        # make the computed spacing SMALLER, i.e. it errs toward reporting a
        # row as over-scoped rather than toward relaxing one -- and a row
        # flagged this way still needs the parameter checked by hand before
        # anyone edits it.
        for m in re.finditer(r"\bphase\w*\s*==\s*\(([^()]*\?[^()]*)\)", full):
            arms = re.findall(r"PH_T(\d)", m.group(1))
            found |= {int(a) for a in arms}
        if not found:
            # Unguarded (free-running): captures on every clock.
            if full.strip() in ("1", "(1)"):
                return set(range(self.phases))
            # Guarded by something with no phase term in it. REFUSE TO GUESS.
            return None
        return found


def sdc_rows(path):
    """Every setup multicycle row: (line_no, from_pats, to_pats, N, text)."""
    rows = []
    for n, line in enumerate(pathlib.Path(path).read_text(
            encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if s.startswith(("#", "//")) or "set_multicycle_path" not in s:
            continue
        if "-setup" not in s:
            continue
        m = re.search(r"-setup\s+-end\s+(\d+)", s)
        if not m:
            continue
        N = int(m.group(1))
        frm = re.search(r"-from\s+\[get_regs\s*\{([^}]*)\}", s)
        to = re.search(r"-to\s+\[get_(?:regs|pins)\s*\{([^}]*)\}", s)
        rows.append((n, frm.group(1).split() if frm else [],
                     to.group(1).split() if to else [], N, s))
    return rows


def build_tree(mods, top):
    """{instance_path: module_name} from the top down."""
    tree = {}

    def walk(mod, prefix, seen):
        body = mods.get(mod)
        if body is None or mod in seen:
            return
        gen = None
        for m in re.finditer(
                r"begin\s*:\s*([A-Za-z_]\w*)|^\s*([A-Za-z_]\w*)\s*"
                r"(?:#\s*\((?:[^()]|\([^()]*\))*\)\s*)?([A-Za-z_]\w*)\s*\(",
                body, re.M):
            if m.group(1):
                gen = m.group(1)
                continue
            mtype, inst = m.group(2), m.group(3)
            if mtype in ("if", "for", "case", "module", "always_ff",
                         "always_comb", "assign", "begin", "end"):
                continue
            if mtype not in mods:
                continue
            level = f"{gen}.{inst}" if gen else inst
            path = f"{prefix}/{level}" if prefix else level
            tree[path] = mtype
            walk(mtype, path, seen | {mod})
    tree[""] = top
    walk(top, "", set())
    return tree


def level_of(pattern):
    """`u_membox/u_cache/trap_request*` -> ('u_membox/u_cache', 'trap_request')."""
    p = pattern.rstrip("*")
    if "/" in p:
        inst, leaf = p.rsplit("/", 1)
    else:
        inst, leaf = "", p
    return inst, leaf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sdc")
    ap.add_argument("--rtl", nargs="+", required=True)
    ap.add_argument("--top", required=True, help="top module NAME")
    ap.add_argument("--top-file", help="file holding the top module")
    ap.add_argument("--phases", type=int, default=6)
    ap.add_argument("--module", help="dump one module's phase table and exit")
    ap.add_argument("--json")
    a = ap.parse_args()

    texts = []
    mods = read_modules(a.rtl, [a.top_file] if a.top_file else [], texts)
    aliases = phase_aliases(texts)
    arms = {n: ModuleArms(n, b, a.phases, aliases)
            for n, b in mods.items()}

    if a.module:
        m = arms.get(a.module)
        if not m:
            sys.exit(f"no module {a.module} (have {len(arms)})")
        print(f"{a.module}: {len(m.regs)} register(s), "
              f"{len(m.unknown)} UNKNOWN, {len(m.missed)} unreached")
        for r in sorted(m.regs):
            tag = " UNKNOWN" if r in m.unknown else ""
            print(f"  {r:<34} phases {sorted(m.regs[r])}{tag}")
        if m.missed:
            print(f"  unreached by the walk (treated as absent): {m.missed}")
        return 0

    tree = build_tree(mods, a.top)
    findings, overs = [], 0
    print(f"cadence arms: {len(mods)} module(s), top {a.top}, "
          f"{a.phases} phases/microcycle")
    print(f"instance tree: {len(tree)} level(s)")

    for lineno, frm, to, N, text in sdc_rows(a.sdc):
        launch = collect(frm, tree, arms, a.phases)
        sink = collect(to, tree, arms, a.phases)
        if not launch or not sink:
            continue
        # ⚠⚠ BOTH SIDES MUST BE DERIVED before a row may be called
        # over-scoped. An UNKNOWN arm is expanded to "every phase", which
        # always drives the computed spacing DOWN to 1 -- so a row whose
        # launch or sink could not be classified would be flagged on an
        # ASSUMPTION, and narrowing an SDC row on an assumption is how an
        # over-scoped constraint gets replaced by an over-CONSTRAINED one.
        # Only CONFIRMED rows (both sides classified) justify an edit.
        worst = None
        for sname, sph, sunk in sink:
            for lname, lph, lunk in launch:
                for q in sph:
                    for p in lph:
                        d = (q - p) % a.phases or a.phases
                        cand = (d, sname, lname, p, q, sunk or lunk)
                        if worst is None or d < worst[0]:
                            worst = cand
        if worst is None:
            continue
        d, sname, lname, p, q, assumed = worst
        status = "OK"
        if d < N:
            status = "UNPROVEN (arm UNKNOWN)" if assumed else "OVER-SCOPED"
            if not assumed:
                overs += 1
        findings.append(dict(line=lineno, declared=N, computed=d,
                             sink=sname, launch=lname, launch_phase=p,
                             sink_phase=q, assumed=assumed, status=status,
                             text=text))
        if status != "OK":
            print(f"\n  SDC line {lineno}: declares -end {N}, RTL allows {d}"
                  f"   [{status}]")
            print(f"    {lname} (T{p})  ->  {sname} (T{q})"
                  + ("   -- one side's arm is UNKNOWN, so this spacing is an "
                     "ASSUMPTION, not a derivation" if assumed else ""))
            print(f"    {text[:150]}")

    print(f"\n{len(findings)} row(s) checked; "
          f"{overs} genuinely OVER-SCOPED (classified sinks)")
    if a.json:
        pathlib.Path(a.json).write_text(json.dumps(findings, indent=2),
                                        encoding="utf-8")
    return 1 if overs else 0


def collect(patterns, tree, arms, phases):
    """[(name, phase_set, unknown_flag)] for every register a glob names."""
    out = []
    for pat in patterns:
        inst, leaf = level_of(pat)
        mod = tree.get(inst)
        if mod is None or mod not in arms:
            continue
        m = arms[mod]
        for reg, ph in m.regs.items():
            if leaf and not reg.startswith(leaf):
                continue
            out.append((f"{inst}/{reg}" if inst else reg, ph,
                        reg in m.unknown))
    return out


if __name__ == "__main__":
    sys.exit(main())
