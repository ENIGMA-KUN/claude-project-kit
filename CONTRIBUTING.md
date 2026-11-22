# Contributing

Thanks for looking. Small fixes, new hooks, better docs and reports from real projects are all welcome.

## Ground rules for every change

The kit makes Claude Code change its own setup over time. That only stays safe if a few properties hold, so pull requests that break them will be asked to change:

1. A human approves anything that reaches always-on context (`CLAUDE.md`, rules, skills, hooks, settings). Loops may propose; they never promote themselves. See [the constitution](template/.claude/constitution.md).
2. Claims need evidence. Acceptance in skills and agents is based on commands, exit codes and diffs, not on a model saying it is done.
3. No runtime dependencies. `kg.py`, `ledger.py`, `kit_hook.py` and `install.py` use the Python standard library only and must run on Python 3.8.
4. Hooks fail open and stay fast. A bug in a hook must never block a session; it logs to `.claude/kit/state/hook-errors.log`. `UserPromptSubmit` and `PreToolUse` handlers should finish well under a second.
5. Nothing leaves the machine. No network calls from hooks or tools; signals and ledgers stay local and are redacted for secrets.
6. Small always-on footprint. New behaviour belongs in a skill, a path-scoped rule or the knowledge graph before it belongs in `CLAUDE.md`.
7. Never overwrite user files. The installer upgrades kit-managed files with a backup and parks everything else in `.claude/kit/incoming/`.

## Repository layout

| Path | What lives there |
|------|------------------|
| `template/` | Everything copied into a project. Edit files here, not in an installed copy |
| `template/.claude/kit/kg.py` | Knowledge graph engine: parse, validate, BM25 search, drift, signals, doctor |
| `template/.claude/kit/ledger.py` | Task ledger and resume brief |
| `template/.claude/hooks/kit_hook.py` | One dispatcher for every hook event |
| `template/.claude/skills/`, `agents/` | Skills and agents (Markdown with YAML frontmatter) |
| `install.py` | Installer; `install.ps1` and `install.sh` only find Python and call it |
| `.claude-plugin/`, `plugin/` | Plugin and marketplace manifests and the `adopt` skill |
| `tests/smoke_test.py` | End-to-end test: builds a throwaway project, installs the kit, drives every hook with recorded payloads |
| `examples/sample-project/` | A filled-in knowledge graph used in the docs |
| `docs/` | Reference docs and the SVG diagrams |

## Development setup

```bash
git clone https://github.com/ENIGMA-KUN/claude-project-kit.git
cd claude-project-kit
python tests/smoke_test.py
python template/.claude/kit/kg.py --root examples/sample-project validate
```

No virtual environment is needed. To try your change in a real project, run `python install.py /path/to/a/test-repo`, open Claude Code there and run `/kit-init`. To test the plugin locally: `claude --plugin-dir .` from the repository root, then `/project-kit:adopt` in another folder.

If you touch the plugin manifests, run `claude plugin validate .`.

## Making a change

1. Open an issue first for anything larger than a bug fix, so we can agree on the shape before you write it.
2. Branch from `main` (`fix/...`, `feat/...`, `docs/...`).
3. Add or update a check in `tests/smoke_test.py` for any behaviour you change. Hook changes need a recorded payload in the test.
4. Run the smoke test on the oldest Python you have (3.8 ideally) and on a recent one.
5. Update `CHANGELOG.md` under "Unreleased" and the docs that describe the behaviour.
6. Open a pull request with a short summary, what changed, and how you tested it.

Commit messages: imperative mood, under 72 characters, no trailing period (`Add PowerShell guard for Format-Volume`).

Writing style for docs, skills and comments: plain words and concrete claims. Comments explain why, not what. Skills are instructions to a model, so keep them specific and short; every extra line costs context in every session that loads them.

## Good first issues

These are real gaps, roughly in order of usefulness:

- More `PreToolUse` guard patterns with tests (PowerShell, database CLIs, cloud CLIs such as `aws s3 rm --recursive`).
- More secret patterns in `kg.py` `SECRET_RULES` (Stripe, Azure, GCP service accounts), each with a positive and a placeholder test.
- Correction and decision phrase detection for languages other than English.
- A `kg.py html` command that writes a self-contained interactive graph view.
- `AGENTS.md` and Codex/Cursor support: an init path that writes the knowledge index pointer into `AGENTS.md`.
- A transcript adapter in `ledger.py` for another agent's session format.
- Optional embedding search behind a flag, keeping BM25 as the default and the engine dependency-free when the flag is off.
- macOS and Linux reports from real projects (the suite runs there, but most hands-on testing so far is on Windows).

## Reporting how the kit behaved on your project

The most valuable contribution is evidence from real use. Use the "Kit feedback" issue form and include, if you can:

- the kind of project (language, size, team or solo),
- the output of `python .claude/kit/kg.py doctor` and `python .claude/kit/kg.py signals --days 14`,
- what `/kit-init` got wrong or missed, and the note it wrote to `kit-feedback.md`.

Strip anything private first. Signals are redacted for common secret shapes, but prompts can still contain names and paths.

## Code of conduct

Participation is covered by the [Code of Conduct](CODE_OF_CONDUCT.md).
