---
type: proposal
title: "Ask before pip install in this repo"
description: "The uv lesson was recalled twice but pip install still ran once; escalate from prose to a PreToolUse hook."
tags: [uv, hook, tooling]
status: proposed
confidence: medium
source: "curator, /curate 2026-11-20"
created: 2026-11-20
updated: 2026-11-20
review_by: 2026-12-20
target: .claude/settings.json
control: hook
scope: project
times_proposed: 1
evidence: ["tool_failure Bash[pip] 2026-11-19", "correction 2026-11-18"]
relations:
  related: [lessons/use-uv-not-pip]
---

## Change

Add a PreToolUse rule that returns `permissionDecision: ask` for Bash commands matching `(^|\s)pip3? install\b`, with the reason "This repo uses uv: try `uv add <pkg>`."

## Evidence

- 2026-11-18: correction "no, we use uv" after `pip install httpx`.
- 2026-11-19: `pip install -e .` failed in session 4b1c (lesson had been recalled in that session).
- Lesson `lessons/use-uv-not-pip`: recalled 2 times, trigger recurred 1 time since creation.

## Diagnosis

The lesson reaches the context but loses to the pip habit under time pressure. A deterministic check at the tool boundary cannot be ignored.

## Constitution check

C1: needs approval, requested here. C3 and C10 unaffected. No secrets involved (C7).

## Decision

