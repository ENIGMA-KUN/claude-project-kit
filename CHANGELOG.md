# Changelog

All notable changes to this project. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [semantic versioning](https://semver.org/).

## [Unreleased]

## [1.2.0] - 2026-11-27

### Added

- Research-integrity guard: `research.protected_paths` in config, a pre-tool check that asks before protected evaluation data, test sets, metric code or baselines are edited, moved, overwritten or deleted, and `runlog.py` to fingerprint them and log every experiment run with seed, commit, data fingerprints and metrics.
- `/experiment` skill to set up the guard, run and report experiments, and trace every reported number to a logged run.
- Optional second opinion from a different model: `review.py` and the `/second-opinion` skill send a secret-scanned review packet to a command you configure and record its verdict. Off by default.
- The verifier checks research integrity and, when enabled, includes the second opinion; either REJECT rejects.
- Constitution invariants C12 (evaluation is fixed) and C13 (second opinion is opt-in).
- `kg.py doctor` reports the research guard and second-opinion status.

## [1.1.0] - 2026-11-22

### Added

- Claude Code plugin and marketplace manifests: `/plugin install project-kit --marketplace ENIGMA-KUN/claude-project-kit`, then `/project-kit:adopt` in any project.
- Task ledger per git branch (`ledger.py`): goal, decisions with status, dead ends, open questions and next step, put back into context after compaction and offered after `/clear`.
- Resume brief built from the session transcript on PreCompact, Stop and SessionEnd.
- Automatic decision capture from `Decision:` lines, user phrases such as "let's go with", and AskUserQuestion answers.
- `/decide` skill to record, review, approve, change and promote decisions.
- The verifier checks work against approved decisions and recorded dead ends; the curator looks for dead ends repeated across tasks.
- `/kit-init` support for non-code folders (papers, docs, research notes, data analysis).
- Open-source files: contributing guide, code of conduct, security policy, issue forms, pull request template.

### Changed

- The sample knowledge graph in the README is an SVG, readable in GitHub's light and dark themes.
- `kg.py mermaid` sets an explicit text colour so exported graphs stay readable in dark themes.
- The installer adds any missing `.gitignore` entries on upgrade, not only on first install.

## [1.0.0] - 2026-11-21

### Added

- Adaptive `/kit-init`, knowledge graph engine (`kg.py`) with BM25 search, validation, drift and staleness checks.
- Hooks for knowledge recall, correction and failure logging, the three-failure loop budget, destructive command and secret guards.
- Skills: `/learn`, `/reflect`, `/curate`, `/handoff`, `/loop-contract`, `/audit`, `recall`. Agents: `verifier`, `curator`.
- Constitution, installer for Windows, macOS and Linux, sample project, end-to-end smoke test.
