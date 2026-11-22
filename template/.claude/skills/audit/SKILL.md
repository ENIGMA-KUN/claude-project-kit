---
name: audit
description: Quarterly context audit. Measures the always-on instruction budget, classifies every CLAUDE.md and rule line as keep, update, archive or delete, finds duplicates and contradictions, moves subsystem rules to path-scoped files, runs the canary probes, and estimates the context maturity level.
disable-model-invocation: true
effort: high
---

# Context audit

Rules accumulate and are rarely removed. Each stale or conflicting line still costs context in every session and biases work toward outdated patterns. Run this every quarter, after a major refactor, or when Claude starts ignoring rules.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## 1. Measure

```
python .claude/kit/kg.py doctor
python .claude/kit/kg.py validate
python .claude/kit/kg.py stale
python .claude/kit/kg.py signals --days 90
```

Count lines and estimate tokens for `CLAUDE.md`, `~/.claude/CLAUDE.md` (read only; it belongs to the user, report on it but do not edit), and every `.claude/rules/*.md` without `paths:`.

## 2. Classify every rule

For each instruction line in CLAUDE.md and the always-on rules, check:

1. Relevance: still true for the current stack and code? (grep for the libraries, commands and paths it names)
2. Specificity: would Claude, with no project context, do something different without it?
3. Enforceability: could a formatter, linter, type, test or hook enforce it? Then it belongs there, not in prose.
4. Conflicts and duplicates: does another rule say the same or the opposite?
5. Placement: is it subsystem-specific? Then it belongs in a path-scoped rule. Is it a procedure? Then a skill. Is it a fact? Then a knowledge node.

Label each KEEP, UPDATE, MOVE (with destination), ARCHIVE or DELETE, with a one-line reason.

## 3. Ejection candidates

From the signals summary: lessons never injected in 90 days and with no recurrence, skills nobody invoked (`/skill-doctor` in a terminal shows this on recent Claude Code versions), hooks that never fired. These are candidates, not verdicts: a rule can be silent because it works. Ask before removing anything protective.

## 4. Canaries

Read `.claude/kit/canaries.md`. For each probe, judge whether current instructions would produce the pass behaviour. If the user wants an empirical run, give them the commands to run each prompt in a fresh headless session (`claude -p "<prompt>"`) before and after the changes, and compare.

## 5. Propose and apply

Write the report to `.claude/kit/reports/audit-<YYYY-MM-DD>.md`: measurements, the classification table, ejection candidates, canary assessment, maturity level, and the proposed diff. Present the changes with AskUserQuestion grouped by kind (deletes and archives, moves, rewrites). Apply only what is approved. Archived rules go to `.claude/CLAUDE-archive.md` as:

```
### [Retired <YYYY-MM>] <rule>
Replaced by: <new location or "nothing">
Reason: <why>
```

Then rebuild and validate the graph, log the audit with `python .claude/kit/kg.py log "audit: ..."`, and report the before and after token budget.
