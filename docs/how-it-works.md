# How the kit works

## Hook events

All hooks call one dispatcher, `.claude/hooks/kit_hook.py <event>`. Each handler fails open.

| Claude Code event | Handler | Effect |
|-------------------|---------|--------|
| `SessionStart` (startup, resume, clear, compact) | `session-start` | Adds a short `[project-kit]` note: whether `/kit-init` is still needed, graph counts, stale nodes, pending proposals, the three newest lessons, the latest handoff, git branch and changed-file count, and whether `/curate` is due. After compaction it reminds Claude to re-read the active loop contract. Also deletes per-session state older than seven days. |
| `UserPromptSubmit` | `prompt` | Detects corrections ("no, that's wrong", "I told you", "you keep...") and logs them. Runs BM25 over active nodes and injects up to three matches as one-line pointers. A node is injected at most once per session. Slash commands are skipped; `/learn` and `/reflect` mark the session as reflected. |
| `PreToolUse` (Bash, PowerShell, Edit, Write, MultiEdit) | `pre-tool` | Denies or asks on destructive commands; asks before edits to the constitution; denies secrets written into knowledge or instruction files. |
| `PostToolUseFailure` | `tool-failure` | Logs the failure with a normalised pattern key (paths, numbers and quoted strings removed). On the third identical failure in a session (and the sixth) it tells Claude the loop budget is spent. |
| `PreCompact` | `pre-compact` | Logs a context-pressure signal. |
| `Stop` | `stop` | Once per session, when failures plus twice the corrections reach the threshold and no `/reflect` or `/learn` ran, shows you a one-line suggestion. Never blocks. |
| `SessionEnd` | `session-end` | Logs a one-line summary: failures, corrections, nodes injected, reflected or not. |

## Retrieval

Queries in a coding session are lexical: error strings, commands, file and function names. BM25 handles those well with no embedding service. Each node is indexed with weights: title x3, trigger x3, tags x2, description x2, rule x2, paths and body x1.

Settings in `.claude/kit/config.json` under `retrieval`:

| Key | Default | Meaning |
|-----|---------|---------|
| `enabled` | `true` | Turn per-prompt injection off without removing the hook |
| `max_nodes` | `3` | Upper bound per prompt |
| `min_score` | `3.0` | BM25 score floor; raise it if injections feel noisy |
| `min_terms` | `2` | Distinct query terms a node must match |

Only `status: active` nodes are served. Candidates and proposals never reach a session until approved.

## Signals

`.claude/kit/signals/events.jsonl`, one JSON object per line, local and gitignored.

| event | category | fields |
|-------|----------|--------|
| `tool_failure` | syntactic or procedural | `tool`, `key`, `text` (command or file, then error excerpt) |
| `correction` | semantic | `text` (prompt excerpt) |
| `interrupt` | semantic | `tool` |
| `guard` | alignment | `tool`, `text` (reason) |
| `compact` | performance | `trigger` |
| `injected` | | `nodes` |
| `session_start`, `session_end` | | counts |

All text is passed through the secret patterns before it is written. `kg.py signals` aggregates the window: events by kind, top failure patterns with session counts, recent corrections, and per-lesson injection counts against recurrences of the lesson's `trigger` words since the lesson was created.

## Proposal lifecycle

```
/reflect or curator  -->  knowledge/_inbox/<date>-<slug>.md  (status: proposed, times_proposed: 1)
       |                                   |
       |   seen again                      |  /curate presents it with evidence
       +--> times_proposed += 1            v
                                 accepted | rejected (reason kept) | deferred (date)
                                 at times_proposed >= 3 a decision is required
```

Each proposal names its `target` file, its `control` level and its `scope`. `scope: kit` proposals are copied to `FEEDBACK.md` in the kit folder so the template improves across projects.

## Control ladder

When a problem recurs, the curator proposes the strongest control that can catch it:

1. Test, type or lint rule
2. Hook
3. Skill
4. Path-scoped rule (`.claude/rules/*.md` with `paths:`)
5. Knowledge node
6. Line in `CLAUDE.md`

Prose is the last resort because it is the only control that has to be remembered.

## Maturity levels

`kg.py doctor` estimates where the project stands, following the context engineering guide:

| Level | Meaning | What the kit checks |
|-------|---------|---------------------|
| 0 | No configuration | no `CLAUDE.md` |
| 1 | Flat config | `CLAUDE.md` exists |
| 2 | Structured | three or more sections, at most 200 lines |
| 3 | Modular | path-scoped rules or five or more active nodes |
| 4 | Measured | three or more canaries and signals being recorded |
| 5 | Engineered | `/curate` in the last 30 days and an audit report on file |

## Limits

- Retrieval is lexical. A question phrased with none of a node's words will miss it; good `trigger` and `tags` fields matter.
- Signals are per machine. Teams that want cross-developer analysis need to export them deliberately.
- Correction detection is a regex. It misses polite corrections and sometimes flags an instruction that starts with "don't". The cost of a false positive is one log line and a gentle suggestion.
- The hooks were tested with recorded event payloads and the exact `settings.json` command strings; run `/kit-init` and watch the first sessions to confirm they fire in your Claude Code version (`kg.py signals --days 1` shows what was recorded).
- Nothing here proves a lesson improved outcomes. The injection and recurrence counts are there so you can check.
