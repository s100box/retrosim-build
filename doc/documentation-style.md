# Release documentation conventions

<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

## README structure

Use the repository or component name as the title, followed by the SPDX
comments and a short description. Use these second-level sections in order:

1. Documentation: links and the subject owned by each document.
2. Repository layout: a short path table, without module-level behavior.
3. Requirements: tools, supported versions, and required or optional siblings.
4. Getting started: the shortest useful setup or integration procedure.
5. Verification: commands, prerequisites, expected verdicts, and hook behavior.
6. License: links to the applicable license texts and any exceptions.

Subsystem READMEs use the same order and link to shared requirements and
license information. State the working directory before command blocks.
Keep safety constraints beside commands that need them.

## Design document structure

Use `<project> design` as the title, SPDX comments, a README backlink, and a
contents list. Number technical sections and use sentence-case headings.
Begin with purpose and scope, describe architecture and component contracts,
then document verification and measured hardware limits. The detailed section
names and order follow the design; preserve section numbers cited by source code.

Use tables for modules, ports, parameters, registers, and test coverage.
Describe current behavior in present tense. Keep design rationale that explains
a constraint or tradeoff; remove development diaries and superseded instructions.
Distinguish simulated, timing-closed, and hardware-validated behavior.

## Information ownership

The README owns setup and entry commands. The design owns interfaces,
architecture, and verification scope. Dedicated guides own long command and
operating references. Generated coverage reports own coverage figures and hole
triage. Link to the owning document instead of copying tables or procedures.
Short orientation summaries and safety reminders may repeat where needed.

Track unresolved work in repository issues. Describe limitations directly in
release documentation; omit private tracker links, hostnames and issue numbers.
Do not maintain `PROGRESS.md` or `COMPLETED.md`. Preserve useful facts and file
open work before removing such logs. Use years or explicit placeholder dates
in examples rather than session-specific dates and times.

Preserve sealed measurement bundles and faithful source transcriptions as
primary evidence, including their original dates, timestamps, identifiers,
and hashes. The editorial cleanup rule does not authorize rewriting those
artifacts or breaking the references that identify them.

## Link maintenance

Use relative Markdown links within a repository. For another repository, use
its public GitHub URL with an explicit branch and file path. If that project
is not published, identify the sibling checkout in plain text instead of
creating a broken link. Update
inbound links when moving a section, and retain explicit anchors where a
published heading changes. Check links and anchors with
`tools/xcheck-links.py --root REPOSITORY --anchors --github-hosted` from the
workspace root. Hosted mode rejects links leaving that checkout, ignored or
untracked targets, and case mismatches that a Windows filesystem would accept.
