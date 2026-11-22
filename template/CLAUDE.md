# {{PROJECT_NAME}}

{{ONE_SENTENCE_DESCRIPTION}}

<!-- /kit-init replaces every {{placeholder}} and removes sections that stay empty.
     Keep this file under 150 lines. Before adding a line, ask: could Claude find this
     by reading the code? If yes, leave it out. -->

## Commands

{{COMMANDS}}

## Stack and layout

{{WHAT: only what is not obvious from the code: package manager quirks, generated folders, entry points}}

## Decisions that shape the code

{{WHY: two to five decisions Claude would otherwise get wrong, each linking its node in knowledge/decisions/}}

## Conventions and gotchas

{{HOW: rules Claude would break by default. Phrase common mistakes as "Never X; do Y". Linter-enforced style does not belong here}}

## How this project learns

- Project knowledge lives in `knowledge/`, a graph of Markdown nodes (architecture, decisions, lessons, solutions, concepts, procedures) linked by typed relations. Before guessing about architecture, a past decision or a recurring error, query it: `{{PY}} .claude/kit/kg.py query "<terms>"`, or use the `recall` skill.
- A hook adds matching nodes to your context on each prompt. Treat them as project facts, read the file before relying on details, and say so when one looks wrong or outdated.
- When the user corrects something that could happen again, fix it, then offer `/learn`. Suggest `/reflect` at the end of a substantial session and `/curate` when the session-start note says the meta loop is due.
- Never write secrets into `knowledge/`, `CLAUDE.md` or `.claude/`. Never edit `.claude/constitution.md`, or promote a candidate into this file or `.claude/rules/`, without the user's explicit approval.

## Working loop

- Done means the verification commands pass, the change meets the stated requirement, and the final message shows the evidence (command and exit status). Your own statement that it works is not evidence.
- Same failure three times: stop, diagnose the cause, or ask. Do not retry the same approach.
- For multi-step, risky or unattended work, write a loop contract first with `/loop-contract`, and hand the result to the `verifier` agent before calling it done.

## Decisions survive context resets

- When you make a choice a later session could reopen, write it on its own line: `Decision: <choice>, because <reason>`. Same for `Dead end: <approach>, because <why it failed>`, and `Next: <step>` when you pause. A hook files these in the task ledger, which comes back after compaction and is offered after `/clear`.
- Approved decisions in the ledger are settled; do not reopen them unless the user does. Get the user's yes before acting on a proposed decision that is costly to reverse. `/decide review` lists what is pending.

## Context index (load on demand)

| File | Contents | When to read |
|------|----------|--------------|
| `knowledge/index.md` | Every active node with a one-line summary | Before design work, or when a topic might already be documented |
| `.claude/kit/code-map.yaml` | Generated repository shape: folders, languages, manifests, instruction files | Before creating files, modules or packages |
| `.claude/constitution.md` | Invariants the learning loops may not change | Before editing rules, skills, hooks or this file |
| `.claude/kit/briefs/<branch>.md` | Resume brief: goal, decisions, dead ends, files, recent turns | After `/clear` or in a new session continuing this branch |
| `.claude/kit/handoffs/` | Session handoffs | When resuming earlier work |
| `.claude/kit/contracts/` | Loop contracts for long tasks | When continuing a contracted task |
