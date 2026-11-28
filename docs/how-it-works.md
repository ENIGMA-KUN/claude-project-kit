# How the kit works

## Hook events

All hooks call one dispatcher, `.claude/hooks/kit_hook.py <event>`. Each handler fails open.

| Claude Code event | Handler | Effect |
|-------------------|---------|--------|
| `SessionStart` (startup, resume, clear, compact) | `session-start` | Adds a short `[project-kit]` note: whether `/kit-init` is still needed, graph counts, stale nodes, pending proposals, the three newest lessons, the latest handoff, git branch and changed-file count, whether `/curate` is due, and new upkeep findings (kit release, flagged tools) once each. Starts the upkeep check in the background when it is due. After compaction it puts the open part of the task ledger back into context; after `/clear`, or on a new session within `stale_days`, it adds a one-line pointer to the ledger and brief. Also deletes per-session state older than seven days. |
| `UserPromptSubmit` | `prompt` | Detects corrections ("no, that's wrong", "I told you", "you keep...") and logs them. Files decision phrases ("let's go with...", "use X instead of Y", "stick with...") as approved decisions and sets the ledger goal from the first substantial prompt. Runs BM25 over active nodes and injects up to three matches as one-line pointers. A node is injected at most once per session. Slash commands are skipped; `/learn` and `/reflect` mark the session as reflected. |
| `PreToolUse` (Bash, PowerShell, Edit, Write, MultiEdit, NotebookEdit) | `pre-tool` | Denies or asks on destructive commands; asks before edits to the constitution or to protected research paths (including shell commands that delete, move, overwrite or edit them in place); denies secrets written into knowledge or instruction files. |
| `PostToolUse` (AskUserQuestion) | `post-tool` | Files each answer as an approved decision: `<header>: <chosen option>`. |
| `PostToolUseFailure` | `tool-failure` | Logs the failure with a normalised pattern key (paths, numbers and quoted strings removed). On the third identical failure in a session (and the sixth) it tells Claude the loop budget is spent. |
| `PreCompact` | `pre-compact` | Logs a context-pressure signal and rebuilds the resume brief from the transcript before the conversation is compacted. |
| `Stop` | `stop`, `brief` (async) | Files `Decision:`, `Dead end:`, `Next:`, `Goal:` and `Question:` lines from Claude's last message into the ledger (lines inside code blocks are ignored). Once per session, when failures plus twice the corrections reach the threshold and no `/reflect` or `/learn` ran, shows you a one-line suggestion. The async `brief` handler refreshes the resume brief at most every two minutes. Never blocks. |
| `SessionEnd` | `session-end` | Logs a one-line summary (failures, corrections, nodes injected, reflected or not) and rebuilds the brief. |

## Task ledger and resume brief

`.claude/kit/ledger/<branch>.json` (with a readable `<branch>.md` next to it) holds working memory for one line of work. Outside git the branch is `default`. Both folders are gitignored; decisions that should outlive the branch are promoted to `knowledge/decisions/` with `/decide promote`.

| Field | Filled by |
|-------|-----------|
| `goal` (with history) | first substantial prompt, `Goal:` lines, `/decide goal`, `/handoff` |
| `decisions` | `Decision:` lines (proposed), user phrases and AskUserQuestion answers (approved), `/decide` |
| `dead_ends` | `Dead end:` lines, `/decide deadend` |
| `questions` | `Question:` lines, `/handoff` |
| `next` | `Next:` lines, `/handoff` |
| `files` | the transcript (Edit, Write, MultiEdit, NotebookEdit) |

Decision statuses: `proposed`, `approved`, `rejected`, `superseded` (with `superseded_by`). Changing a decision adds a new one and supersedes the old; nothing is edited in place.

The brief (`.claude/kit/briefs/<branch>.md`) is rebuilt from the transcript on PreCompact, SessionEnd and, at most every two minutes, on Stop. It holds, in order: a line telling Claude to check the disk before trusting it, the ledger goal, the original request, the latest request, the open part of the ledger, files touched (up to 30) and as many recent turns as fit. The head may use half of the budget (8,000 characters by default, `ledger.brief_max_chars`); the file list shrinks first, then older turns are dropped with a marker. Tool output and Claude's reasoning are never included; each tool call is one line with its target.

Settings under `ledger` in `config.json`: `enabled`, `capture_user_decisions`, `brief_max_chars`, `compact_inject_chars` (default 3,000) and `stale_days` (default 7) for the new-session pointer.

## Research guard

Configured under `research.protected_paths` in `config.json`, usually by `/experiment setup`. The globs name the evaluation surface: held-out data, test sets, metric code, baseline configs, fixed prompts for LLM evaluation.

| Piece | What it does |
|-------|--------------|
| `pre-tool` hook | Asks the user before any Edit, Write or notebook edit to a protected path, and before shell commands that delete, move, overwrite (`>`, `tee`, `cp` onto it) or edit one in place (`sed -i`). Reading is not affected |
| `runlog.py baseline` | Fingerprints every protected file (SHA-256; files over 64 MB by size and timestamp) into `.claude/kit/research-baseline.json` |
| `runlog.py check` | Lists files changed, added or removed since the baseline; exits 1 if any |
| `runlog.py run --name N -- CMD` | Runs the experiment and appends to `.claude/kit/runs.jsonl`: command, commit (and whether the tree was dirty), seed, exit code, duration, protected fingerprints, changes during the run, metrics parsed from `name: value` lines, JSON lines or `--metrics-file`, and a redacted output tail |
| `runlog.py report` | Markdown table of every run of an experiment, failed ones included |
| `runlog.py find --metric M --value V` | Finds the run behind a reported number; exits 1 when none exists |
| `runlog.py compare A B` | Shows differences in seed, commit, command, protected fingerprints and metrics |

The verifier uses `check`, `find`, `compare` and `report` before accepting research work. Commit `research-baseline.json` and `runs.jsonl` if collaborators should be able to check results; they are not gitignored.

## Second opinion review

`review.py` sends a review packet to a different model through a command you configure:

```json
"second_opinion": {"enabled": true, "command": "codex exec -", "timeout_s": 900, "max_diff_chars": 60000}
```

| Tool | Example command | Input |
|------|-----------------|-------|
| Codex CLI | `codex exec -` | stdin |
| Gemini CLI | `gemini -p "Review the change described in the input and answer in the format it asks for."` | stdin appended to the prompt |
| Claude, another model | `claude -p --model opus` | stdin |
| Anything that wants a file | `mytool --input {prompt_file}` | the packet file |

Check each tool's `--help`; flags change between versions.

The packet contains review instructions, the requirement, the diff since `--base` (or the uncommitted changes, or the last commit), new untracked files, the task ledger's open items and, when research paths are protected, the output of `runlog.py check` and the recent runs. Files that usually hold secrets (`.env*`, keys, certificates, `secrets/`, `credentials*`) are left out, and the whole change is scanned with the kit's secret patterns before anything is sent; a hit stops the review with exit code 4. Packets and answers are saved in `.claude/kit/reviews/` (gitignored).

The reviewer must answer `VERDICT: ACCEPT`, `REJECT` or `ESCALATE` with reasons. Exit codes: 0 accept, 1 reject, 2 escalate or no verdict, 3 not enabled, 4 refused, 5 the command failed or timed out. When enabled, the verifier runs it and treats either REJECT as REJECT and any other disagreement as ESCALATE.

## Upkeep

`upkeep.py` watches two things that go stale quietly: the kit itself, and the outside tools a project depends on.

```json
"upkeep": {"mode": "notify", "interval_days": 7, "source": "ENIGMA-KUN/claude-project-kit", "stale_days": 270}
```

| Mode | Background check | Kit updates |
|------|------------------|-------------|
| `notify` (default) | at most once per `interval_days`, started detached by `session-start` | reported once at the next session start, installed when you run `upkeep.py update` or approve it in `/upkeep` |
| `auto` | same | new minor and patch releases are installed by the background check; a new major version still waits for you |
| `off` | none | only when you run the commands |

The background check never runs when `CLAUDE_KIT_UPKEEP=off` or `CI` is set. It adds no time to session start: the hook reads the cached result and, when the check is due, starts `upkeep.py auto` as a detached process. A finding is shown once, as a message to you and a line for Claude; the same finding is not repeated in later sessions.

Kit version: the latest GitHub release of `source` (falling back to the highest `vX.Y.Z` tag) is compared with `KIT_VERSION` in the installed `kg.py`. `upkeep.py update` downloads that release from codeload.github.com, unpacks only `install.py`, `CHANGELOG.md` and `template/` into a temp folder (rejecting absolute paths, `..` and links), prints the changelog entries since your version, asks, and runs the release's installer. Kit files are backed up to `.claude/kit/backup/<timestamp>/`; files you own go to `.claude/kit/incoming/` as usual. `--from <checkout>` installs from a local copy instead, `--ref <tag or branch>` picks another version, `--dry-run` stops before installing. Point `source` at a fork to update from your own reviewed copy.

Watchlist: `.claude/kit/watchlist.json` (commit it so the team watches the same tools). Each entry names a tool, its role in the project, where to look (`github`, `pypi`, `npm`, `hf`), optionally the version you pin and the license you expect, and alternatives as `OWNER/REPO`.

| Flag | Level | Condition |
|------|-------|-----------|
| `archived` | ACT | GitHub repository archived or disabled, or Hugging Face model disabled |
| `deprecated` | ACT | npm marks the package deprecated |
| `license` | ACT | SPDX id differs from the expected one (the entry's `license`, else the first one seen) |
| `moved` | ACT | the repository now answers under another name |
| `stale` | REVIEW | no commits for `stale_days` |
| `update` | UPDATE | the latest release is newer than `pinned` |
| `release` | UPDATE | a new release since the last check (no pin set) |
| `error` | ERROR | the source could not be reached, usually GitHub's limit of 60 unauthenticated requests an hour |

For tools at ACT or REVIEW, every listed alternative is checked the same way, so an inactive project is never offered as the replacement. `upkeep.py probe OWNER/REPO ...` runs that check on any repository, which `/upkeep` uses to compare candidates it found. `watch ack` accepts a license change or a rename after you have reviewed it. `watch preset research` adds a starting stack for research agents; the kit repository re-checks every preset entry weekly in CI, so a preset that goes stale fails the build.

Requests: `api.github.com`, `codeload.github.com`, and `pypi.org`, `registry.npmjs.org` or `huggingface.co` for watched packages. They carry repository and package names only. `GITHUB_TOKEN` or `GH_TOKEN`, when set, is sent to `api.github.com` alone. Results stay in `.claude/kit/state/upkeep/` (gitignored).

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
| `decision` | | `source` (`markers` or `ask`), `ids` |
| `second_opinion` | | `verdict` (ACCEPT, REJECT, ESCALATE, NONE, refused, timeout) |
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
- Decision capture is pattern-based too. User phrases are filed only for explicit forms ("let's go with", "use X instead of Y", "stick with"); Claude's choices are filed only when it writes a `Decision:` line, which the `CLAUDE.md` rule asks for but cannot force. `/decide review` is where you catch what was missed or misread.
- The brief parser reads Claude Code's transcript format as of late 2026 (one JSON object per line with `type`, `message.content` blocks and `toolUseResult`). A format change makes the brief thinner, never breaks the session: the ledger itself does not depend on the transcript.
- The hooks were tested with recorded event payloads and the exact `settings.json` command strings; run `/kit-init` and watch the first sessions to confirm they fire in your Claude Code version (`kg.py signals --days 1` shows what was recorded).
- Nothing here proves a lesson improved outcomes. The injection and recurrence counts are there so you can check.
- Upkeep reads activity, releases and license ids, not quality. A busy repository can still be the wrong tool, and a quiet one can be finished rather than abandoned; `/upkeep` puts those calls to you. The kit download is trusted on GitHub's TLS and the source repository, with no separate signature: use a fork as `source` if you want to review releases before they reach your projects.
