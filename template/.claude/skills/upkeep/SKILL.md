---
name: upkeep
description: Check for kit updates and for changes in the outside tools this project relies on (new releases, archived or deprecated repositories, license changes, inactive projects), install kit updates with the user's yes, and compare maintained alternatives for flagged tools. Use when the session-start note mentions upkeep, when the user asks about updates, outdated tools or alternatives, or before the project adopts a new outside tool.
argument-hint: "[check | update | alternatives <tool> | watch <tool> | preset research]"
effort: medium
---

# Upkeep

Arguments: `$ARGUMENTS`

Two things go stale without anyone noticing: the kit itself, and the outside tools the project depends on (crawlers, parsers, model runtimes, SDKs, services). `.claude/kit/upkeep.py` checks both. A background check runs at most once a week (`upkeep.mode` in `.claude/kit/config.json`) and the next session start reports anything new once.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs. Every check makes GET requests to GitHub and package registries and sends nothing from the project.

## 1. Check

`python .claude/kit/upkeep.py check` (or `upkeep.py report` to reread the last result without the network). Show the report as it is. Levels:

| Level | Meaning | What to do |
|-------|---------|------------|
| ACT | archived, deprecated, renamed, or license changed | Section 3 now |
| REVIEW | no commits for `stale_days` | Section 3 when the tool matters to the project |
| UPDATE | new release, or newer than the pinned version | Mention it; upgrading the dependency is normal project work |
| ERROR | could not reach the source | Usually the GitHub rate limit; suggest setting `GITHUB_TOKEN`, or retry later |

## 2. Kit update

When the report shows a newer kit:

1. `python .claude/kit/upkeep.py update --dry-run` downloads the release and prints the changelog entries since the installed version. Summarise them for the user in a few lines. For a new major version, list anything that reads like a breaking change.
2. Ask for a yes. Do not install without it, even when the update looks small.
3. `python .claude/kit/upkeep.py update --yes`. The installer backs up every kit file it replaces to `.claude/kit/backup/<timestamp>/` and never overwrites files the user owns; newer versions of `CLAUDE.md`, `settings.json` or the constitution go to `.claude/kit/incoming/`.
4. If anything landed in `incoming/`, run `/kit-init --refresh` to merge it. Then tell the user to restart Claude Code so new hooks and skills load.

Installing from a fork or a local checkout: set `upkeep.source` to `OWNER/REPO`, or run `upkeep.py update --from <path to kit checkout>`. Never switch `upkeep.mode` to `auto` unless the user asks for it: auto mode installs minor and patch releases without review (constitution C14).

## 3. A flagged tool: compare alternatives

For each tool at ACT or REVIEW:

1. Say what changed, with the evidence from the report (archived date, last commit, old and new license).
2. The report already checked the listed alternatives. If none is healthy, or none is listed, find candidates: search the web and GitHub for tools with the same role (the watchlist `role` field says what the tool does here), including awesome lists and the flagged project's own README or issues, which often name a successor. Keep two to four candidates.
3. Compare them with `python .claude/kit/upkeep.py probe OWNER/REPO OWNER/REPO ...`, then judge fit yourself: does it cover what this project uses the tool for (grep the code for imports and calls), is the license compatible with the project, how big is the migration, is the API stable. Cite a source for each claim.
4. Recommend one of: keep (the flag does not matter here, say why), pin the current version, or switch. Switching a dependency is the user's decision. Record the outcome as `Decision: <choice>, because <reason>`; for a lasting choice offer `/learn` so it becomes a decision node.
5. Update the watchlist once the user agrees: `upkeep.py watch add <tool> --alt OWNER/REPO --alt OWNER/REPO`, `upkeep.py watch remove <tool>` after a switch, or `upkeep.py watch ack <tool>` to accept a license change or a rename after review.

A license change is a legal question as much as a technical one. Report the old and new license and where the change was announced; do not tell the user the new license is fine for their use.

## 4. Watch a tool

When the project adopts an outside tool, or the user asks to watch one:

`python .claude/kit/upkeep.py watch add <name> --github OWNER/REPO [--pypi PKG | --npm PKG | --hf MODEL] --role "<what it does here>" --alt OWNER/REPO --pinned <version in use>`

For research-agent projects, `upkeep.py watch preset research` adds a starting stack (metasearch, crawlers, PDF parsers, agent loops, model runtimes, a benchmark). Remove what the project does not use. `watch list` shows the current list. The watchlist (`.claude/kit/watchlist.json`) is meant to be committed so the whole team watches the same tools; the check results stay local.
