---
name: handoff
description: Save the current session state to a handoff file before stopping mid-task, or resume from the latest handoff, task ledger and resume brief (also after /clear). Captures goal, scope, files, discoveries, verified work, status and ordered next steps so a fresh session can continue without re-reading everything.
argument-hint: "[save|resume] [short title]"
disable-model-invocation: true
effort: low
---

# Handoff

Arguments: `$ARGUMENTS`. First word `resume` means resume; anything else means save.

## Save

Create `.claude/kit/handoffs/<YYYY-MM-DD-HHMM>-<slug>.md` (folder is gitignored; personal by default):

```markdown
# Handoff: <title> (<YYYY-MM-DD HH:MM>)

## Task
<one sentence: what is being accomplished and for whom>

## Scope
<in scope, out of scope, acceptance criteria; base commit `git rev-parse --short HEAD`; branch; loop contract path if any>

## Files
- `path/to/file:line`: why it matters

## Discoveries
- <non-obvious facts the next session needs; mark which are verified>

## Work done (with evidence)
- [x] <step> (commit abc1234, or "uncommitted"); check run: `<command>` exit <n>

## Status
<what works, what is broken, what is half-done; last observed time>

## Next steps
1. <exact next action, specific enough to start without re-reading the conversation>

## Open questions
- <decisions waiting on the user>
```

Only list checks you actually ran in this session. Then look at the Discoveries: anything durable (true beyond this task) is a `/learn` candidate; offer it in one line.

Keep the task ledger in step with the handoff, since it is what comes back automatically after compaction or `/clear`:

```
python .claude/kit/ledger.py goal "<current goal>"
python .claude/kit/ledger.py next "<first next step>"
python .claude/kit/ledger.py question "<each open question>"
```

Decisions and dead ends from this session should already be there; check with `python .claude/kit/ledger.py show` and add any that are missing (`/decide`).

## Resume

1. Read the newest file in `.claude/kit/handoffs/` (or the one whose title matches the argument), the task ledger (`python .claude/kit/ledger.py show`) and the resume brief for this branch (`.claude/kit/briefs/<branch>.md`). If there is no handoff, the ledger and brief are enough: they are built automatically.
2. Check their claims against the repo before trusting them: `git log --oneline <base>..HEAD`, `git status --short`, do the listed files exist, does the last recorded check still pass. The brief is history; the files are the present.
3. If a loop contract is referenced, read it.
4. Summarise for the user in under ten lines: goal, approved decisions that constrain the next step, what is verified done, what changed since, proposed decisions still waiting for a yes, and the first next step. Ask before continuing if anything contradicts the handoff or the ledger.
