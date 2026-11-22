---
name: decide
description: Save, update, review and approve decisions for the current task so they survive compaction, /clear and new sessions. Use when a choice is made that a later session could reopen, to change or reverse an earlier decision, to get the user's sign-off on pending decisions, or to promote a decision into the project knowledge graph.
argument-hint: "[\"decision, because reason\"] | review | change D2 \"new decision\" | approve D3 | reject D3 | promote D2 | goal \"...\" | next \"...\""
when_to_use: "A choice was just made; the user asks what was decided; before acting on something costly to reverse; after compaction when decisions feel uncertain."
effort: low
---

# Decisions for the current task

Arguments: `$ARGUMENTS`

The task ledger (`.claude/kit/ledger/<branch>.json`) is working memory for this line of work: goal, decisions, dead ends, open questions and next step. Hooks fill much of it automatically:

- your `Decision: ...`, `Dead end: ...`, `Next: ...` lines are filed as you write them,
- phrases from the user like "let's go with X" are filed as approved,
- every AskUserQuestion answer is filed as an approved decision.

This skill is for doing it on purpose. Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## Statuses

| Status | Meaning | Who sets it |
|--------|---------|-------------|
| `proposed` | Claude's choice, not yet confirmed | Claude |
| `approved` | The user agreed or chose it | the user (directly, via AskUserQuestion, or via this skill) |
| `superseded` | Replaced by a newer decision; kept for history | this skill (`change`) |
| `rejected` | The user said no | this skill |

Approved decisions are settled: do not reopen them unless the user does. Proposed decisions that are costly to reverse (schema, public API, dependency choice, data deletion, architecture) need the user's yes before you act on them.

## Modes

### Record (`/decide "use Redis for the limiter, because it is shared across workers"`)

1. Split the text into the decision and the reason (`because ...`). Ask for the reason if there is none; a decision without a reason gets reopened.
2. If the user typed the command, record it as approved: `python .claude/kit/ledger.py decide "<decision>" --why "<reason>" --status approved --by user`.
3. If you are recording your own choice, record it as proposed (`--status proposed --by claude`). If it is costly to reverse, ask the user right away with AskUserQuestion (options: Approve, Change it, Reject); the answer is filed by the hook, then set the status with step "approve" or "reject" below.
4. Confirm in one line with the id.

### Review (`/decide review`)

1. `python .claude/kit/ledger.py review --json`
2. Show the current goal and ask whether it is still right; if not, `python .claude/kit/ledger.py goal "<new goal>"`.
3. Present proposed decisions and open questions with AskUserQuestion, up to four per call, one decision per question, most consequential first. Each question states the decision and its reason; options: "Approve", "Reject", "Change" (the user can type the replacement in Other).
4. Apply answers: `status D3 approved`, `status D3 rejected`, or the change flow below. Answer open questions with `python .claude/kit/ledger.py answer Q1 "<answer>"`.
5. Show the result: approved list, dead ends, next step.

### Change (`/decide change D2 "keep IP keys for anonymous users"`)

Never edit a decision in place; history matters when someone asks "why did we switch?".

1. Record the new decision (approved if the user asked for the change): `python .claude/kit/ledger.py decide "<new>" --why "<reason>" --status approved --by user` and note the new id.
2. `python .claude/kit/ledger.py status D2 superseded --by <new id>`
3. Check whether work already done follows the old decision; list what needs to change and ask before changing it.

### Approve or reject (`/decide approve D3`, `/decide reject D3`)

`python .claude/kit/ledger.py status D3 approved` (or `rejected`). For a rejection, ask what to do instead and record that as a new decision.

### Promote (`/decide promote D2`)

Task decisions live as long as the branch. A decision that will matter after this task (architecture, conventions, data definitions) belongs in the knowledge graph:

1. Follow the `learn` skill to write a `decision` node, with the ledger entry as the source (`source: "task ledger <branch> D2, approved <date>"`).
2. `python .claude/kit/ledger.py promoted D2 knowledge/decisions/<slug>.md`

### Goal, next step, dead end

`python .claude/kit/ledger.py goal "..."`, `next "..."`, `deadend "..." --why "..."`. Update the goal whenever the task changes direction; the brief built after compaction leads with it.

## When the task is finished

Offer to promote any approved decision with lasting value, then close the ledger with `python .claude/kit/ledger.py archive`. Archived ledgers stay under `.claude/kit/ledger/archive/` for `/curate`, which looks for dead ends that repeat across tasks.
