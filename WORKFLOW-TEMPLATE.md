# WORKFLOW.md — the shared skeleton

Every retrosim RTL repo's `WORKFLOW.md` follows this section taxonomy so a
developer (or agent) can move between repos without relearning the doc. Keep
the numbers and titles; add repo-specific sections after §6.

```markdown
# WORKFLOW — <repo>

## 1. Lint-first protocol (the gate)
   cd sim && ninja        # Verible syntax + lint + format-check — clean before anything simulates
   How to run `ninja format`, where the lint waivers live (.rules.verible_lint).

## 2. Simulation
   The named ninja targets (`unit` = the fast regression; simulators used and how invoked).

## 3. Differential / self-checking gates
   The repo's correctness gates (oracle co-sims, Klaus/zex suites, chip diffs)
   and what the pre-commit / pre-push hooks run. Bypass: SKIP_GATE=1.

## 4. FPGA build + flash
   ./build.sh <board> [<variant>] [<target>]
     boards:  nano20k | console60k | console138k | mega138kpro   (canonical names)
     targets: lint | sim | synth | rom | gprj | config | prog | prog-flash
   Environment: GWSH, PROGRAMMER_CLI, PROGDEV (host cabling override).
   The build fails iff the shared timing sign-off fails (retrosim-build).
   Per-board silicon notes (consoles, clocks, flash regions) go here.

## 5. What gets committed
   Artifacts policy (impl_* is output; .gprj + process_config are generated-but-committed
   via `./build.sh gprj`, drift-gated in pre-commit).

## 6. One-shot "is everything green?"
   The single command sequence proving the repo healthy from a fresh checkout.
```

Repo-specific material (serial-console recipes, SD-card prep, silicon debug
write-ups, firmware builds) follows as §7+. The shared machinery documented
once in `retrosim-build/README.md` (board table, grammar, sign-off rules,
hook environment) should be referenced, not restated.
