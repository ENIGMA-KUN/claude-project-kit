---
type: decision
title: "Self-improving Claude setup through the project kit"
description: "Project knowledge lives in a reviewed graph under knowledge/; hooks capture friction, humans approve every promotion."
tags: [claude, workflow, knowledge, meta]
status: active
confidence: high
source: "kit installation"
created: {{DATE}}
updated: {{DATE}}
review_by: {{REVIEW_DATE}}
paths: [CLAUDE.md, .claude/constitution.md, knowledge/_schema.md]
relations:
  related: []
---

## Context

Each Claude Code session starts without memory of earlier sessions. Corrections made once tend to be needed again, and a CLAUDE.md that grows by accretion loses signal.

## Decision

Use three feedback horizons:

- Inner loop, every turn: hooks inject matching knowledge nodes, block destructive commands, and stop repeated identical failures after three attempts.
- Session loop: `/learn` after a correction, `/reflect` at the end of substantial sessions, `/handoff` before stopping mid-task.
- Meta loop, about weekly: `/curate` reads the friction signals and the inbox, drafts evidence-backed proposals, checks them against `.claude/constitution.md`, and applies only what the user approves.

Facts go to `knowledge/`, retrieved on demand. Always-on `CLAUDE.md` stays short. Mechanical rules become tests, lint rules or hooks.

## Alternatives rejected

- One large CLAUDE.md: every line costs context in every session, and stale lines bias work.
- A hosted memory service: adds infrastructure and a shared write surface without review; plain files in git give diff, blame and rollback.
- Fully automatic rule writing: self-approved rules turn model confidence into policy (constitution C1).

## Consequences

- Someone has to review proposals. `/curate` keeps that to a short weekly batch.
- Friction signals are local and gitignored, so cross-machine analysis needs an explicit export.
- Revisit this decision when the review date passes: check whether lessons are being injected and whether the failures they target stopped recurring (`python .claude/kit/kg.py signals`).
