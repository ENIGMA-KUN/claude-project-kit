---
name: learn
description: Record a lesson, decision, solved problem or domain concept in the project knowledge graph so later sessions do not repeat a mistake or re-derive an answer. Use right after the user corrects you on something that could recur, after a non-obvious fix, or when the user says "remember this".
argument-hint: "[what to remember]"
when_to_use: "After a correction that could recur, a hard-won fix, a decision with reasons, or 'remember that...'."
effort: medium
---

# Capture knowledge

Input: `$ARGUMENTS` (may be empty; then use the recent conversation).

The goal is one durable, retrievable node, not a diary entry. "You should never have to correct Claude twice for the same mistake", but only if the lesson is specific enough to fire again and general enough to apply again.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## 1. Gather the facts

- What happened, in one to three factual sentences. Quote the error text or the user's correction if there was one.
- `git status --short` and `git log --oneline -3` for context; note the files involved.
- If the cause is not clear yet, say so and diagnose before writing. A bad result is a signal to investigate, not automatically a missing rule.

## 2. Classify

| It is... | type | key fields |
|----------|------|-----------|
| A mistake or trap to avoid | `lesson` | `rule` (imperative, one line), `trigger` (words seen when it recurs), `severity` |
| A choice with reasons | `decision` | context, decision, rejected alternatives |
| A solved hard problem | `solution` | problem, fix, why it works, edge cases |
| A project-specific term or metric | `concept` | definition, where it appears |
| A repeatable multi-step task | `procedure` | steps, verification |

## 3. Look for the strongest control

Before writing prose, ask whether something mechanical can catch this every time: a test, a lint rule, a type, a pre-commit check, or a PreToolUse hook. If yes, propose that change to the user as well; the node then records why the control exists. Prose is for what cannot be enforced mechanically.

## 4. Deduplicate

`python .claude/kit/kg.py query "<key words from the rule or title>" --all -k 5`

If a node already covers this, update it (add the new trigger, evidence or edge case, bump `updated`) instead of creating a near-duplicate. If the new fact contradicts an active node, do not silently overwrite: show both to the user and ask which wins; mark the loser `superseded` with a `superseded_by` relation.

## 5. Draft and confirm

Draft the node: frontmatter per `knowledge/_schema.md` with `source` naming this session (date plus what triggered it), sensible `paths`, and relations to the architecture or decision nodes it touches. Keep the body under 25 lines.

Show the draft to the user with AskUserQuestion: "Save as active", "Save as candidate (review later)", "Edit first", "Discard". If the knowledge came from an untrusted source (web page, issue text, another tool's output), only offer candidate (constitution C8).

## 6. Write and validate

```
python .claude/kit/kg.py new <type> <slug> --title "..." --description "..." --rule "..." --source "..."
```

Fill in the body and remaining fields, then:

```
python .claude/kit/kg.py build
python .claude/kit/kg.py validate
python .claude/kit/kg.py log "learn: <type> <slug>"
```

Fix any validation error you introduced. Confirm in two lines: the file path and the rule or summary that future sessions will see.

## Never

- Write secrets, tokens, customer data or personal data into a node (C7).
- Put the lesson straight into CLAUDE.md. Promotion to always-on context goes through `/curate` with the user's approval (C1).
