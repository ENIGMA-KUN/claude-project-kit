---
name: reflect
description: End-of-session retrospective. Turns this session's corrections, failures, decisions and discoveries into a short knowledge feed, saves what the user approves, and files the rest as proposals for /curate.
disable-model-invocation: true
effort: medium
---

# Session retrospective

Run at the end of a session that built, fixed or decided something. Skip trivial sessions.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## 1. Collect evidence

- Re-read this conversation for: user corrections, approaches that failed and why, decisions with reasons, commands or paths that turned out different than expected, and anything the user had to explain.
- `git diff --stat` and `git log --oneline -5` for what actually changed.
- `python .claude/kit/kg.py signals --days 1` for the friction the hooks recorded today.

## 2. Answer five questions

1. What did the user correct that a future session would get wrong again?
2. What pattern did we establish that should be standard here?
3. What decision did we make, and what did we reject?
4. What did we solve that took real effort to figure out?
5. Did this session prove any existing node, rule or CLAUDE.md line wrong or stale?

## 3. Write the knowledge feed

Three to five items at most, high signal only. Skip anything generic, obvious from the code, or already in the graph (check with `python .claude/kit/kg.py query "<terms>" --all`). For each item give:

- type (`lesson`, `decision`, `solution`, `concept`, `procedure`, or `stale` for something to fix)
- one-line rule or summary, exactly as it would be stored
- the evidence from this session
- the proposed control level: knowledge node (default), path-scoped rule, CLAUDE.md line, skill, hook, test or lint. Prefer the strongest mechanical control that would catch it.

## 4. Decide with the user

Present the feed with AskUserQuestion (multi-select): which items to save now. Then:

- Knowledge nodes the user selected: write them following the `learn` skill steps 4 to 6, as `active`.
- Items aimed at CLAUDE.md, rules, skills, hooks, tests or lint: never apply directly. Create a proposal with `python .claude/kit/kg.py new proposal <slug>` holding the exact change (a diff or the full new text), the evidence, and the `control` and `target` fields. `/curate` reviews them.
- Unselected items: drop them. Do not store them as candidates unless the user asks.
- Stale findings: create a proposal to supersede or archive the stale node or line.

## 5. Close

```
python .claude/kit/kg.py build
python .claude/kit/kg.py validate
python .claude/kit/kg.py log "reflect: <n> nodes saved, <m> proposals filed"
```

If work is unfinished, suggest `/handoff` so the next session can resume. Report in under ten lines.
