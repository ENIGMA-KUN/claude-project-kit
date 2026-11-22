# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: on this repository, open the Security tab and choose "Report a vulnerability". Do not open a public issue for something that could be exploited before a fix is out.

Include what you found, how to reproduce it, and the kit version (`kit_version` in `.claude/kit/config.json`). You will get a reply within a week.

## What is in scope

- Hook behaviour that could run commands, leak data or block a session unexpectedly (`template/.claude/hooks/kit_hook.py`).
- Ways to get text from untrusted sources (web pages, issues, other tools' output) promoted into always-on instructions without human approval.
- Secrets reaching the knowledge graph, the task ledger, the resume brief or the signal log despite the scanners.
- The installer overwriting or deleting user files.

## What the kit does not claim

- The `PreToolUse` guard is a safety net for common destructive commands, not a sandbox. It matches patterns; a determined or obfuscated command can get past it. Use Claude Code's permission settings and sandboxing for real isolation.
- Secret detection is pattern-based. It catches common key formats and assignments, not every secret.
- Hooks run with your user's permissions, like any Claude Code hook. Read `kit_hook.py` before installing it in a sensitive environment; it is one standard-library Python file.
