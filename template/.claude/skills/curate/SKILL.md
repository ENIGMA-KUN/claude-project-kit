---
name: curate
description: Meta loop for the project's Claude setup. Mines friction signals, stale knowledge and pending proposals, drafts evidence-backed changes at the right control level, checks them against the constitution, and applies only what the user approves. Run about weekly or when the session-start note says it is due.
argument-hint: "[--days N]"
disable-model-invocation: true
effort: high
---

# Curate the setup

Arguments: `$ARGUMENTS` (default window: 14 days).

The inner loop catches problems during a task. This loop changes the system so the same problem stops happening. It closes only through the user's decisions: you propose, they approve (constitution C1). A curator that writes reports nobody acts on is an open loop, so keep the batch small and every item decidable.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## 1. Gather (delegate to keep your context clean)

Start the `curator` agent with this brief: "Analyse the last N days of signals and the knowledge graph; write proposals to knowledge/_inbox/ per your instructions; return a summary table." While it works, or if subagents are unavailable, the inputs are:

```
python .claude/kit/kg.py signals --days N
python .claude/kit/kg.py validate
python .claude/kit/kg.py stale
python .claude/kit/kg.py doctor
```

plus every `knowledge/_inbox/*.md` with `status: proposed`.

## 2. Check what the agent produced

Read each new or updated proposal. Reject on sight any that:

- has no evidence (event keys, excerpts, session dates, or a failing command),
- targets `.claude/constitution.md`,
- would add a line to CLAUDE.md that a test, lint rule or hook could enforce instead,
- duplicates or contradicts an active node or rule without saying which should win.

Run the constitution check yourself: read `.claude/constitution.md` and confirm each proposal violates no invariant. Run a conflict check: grep `CLAUDE.md` and `.claude/rules/` for rules on the same topic.

## 3. Apply suppression

If a proposal has `times_proposed` of 3 or more, it must be decided today: accept, reject with a written reason, or defer with a date. Silent repetition is the open-loop failure.

## 4. Present a decision batch

Use AskUserQuestion, at most four questions per call, one proposal per question, most impactful first. Each question states: the change in one line, the evidence in one line, the control level, and the target file. Options: "Apply", "Apply as candidate only" (knowledge nodes), "Reject", "Defer".

Also present, as one multi-select question, ejection candidates from the agent's report: active lessons never injected in the window with no recurrences, nodes stale past review, rules that no session touched. Options per item: keep (bump `review_by`), update, archive.

## 5. Apply accepted changes

- Knowledge nodes: write or edit, set `updated`, then build and validate.
- CLAUDE.md or rules: apply the exact text from the proposal. Keep CLAUDE.md under 150 lines; if it would go over, move something to a path-scoped rule or archive a dormant line into `.claude/CLAUDE-archive.md` with date and reason.
- Skills, hooks, tests, lint config: make the change, then run the relevant verification command from `config.json` and show its result.
- Mark each proposal `status: accepted`, `rejected` (with the reason in its Decision section) or `deferred` (with a date). Keep the files: rejected proposals are evidence for later rounds.
- Proposals with `scope: kit` describe improvements to the kit template itself. Append them to `<kit_home>/FEEDBACK.md` if `kit_home` is set in config, otherwise to `.claude/kit/kit-feedback.md`.

## 6. Self-consistency

Compare what the setup claims with what is true: commands in CLAUDE.md exist in the manifests, paths in the context index exist, the doctor's maturity level matches what CLAUDE.md implies. Fix mismatches (with approval) or file proposals.

## 7. Close the round

```
python .claude/kit/kg.py build
python .claude/kit/kg.py validate
python .claude/kit/kg.py log "curate: <a> accepted, <r> rejected, <d> deferred, <e> archived"
python .claude/kit/kg.py mark-curated
```

Report: decisions made, files changed, verification results, and the one metric to watch next round (for example "pattern X: 9 failures this window; check it drops after the new hook").
