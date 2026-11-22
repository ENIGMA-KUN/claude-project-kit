# Init prompt

## In Claude Code

After installing the kit into the project, run one of:

```
/kit-init            existing codebase
/kit-init --new      new, almost empty repository
/kit-init --refresh  ongoing project, after a kit upgrade or a big change
```

The full procedure lives in `template/.claude/skills/kit-init/SKILL.md` and is copied into each project.

## If the skill did not load, or in another agent

Install the kit first (`install.ps1` or `install.sh`), then paste this into the agent from the project root:

```
Read .claude/skills/kit-init/SKILL.md and follow it step by step for this repository.
Mode: existing project (use --new if the repo is nearly empty, --refresh if
.claude/kit/config.json already says initialized: true).

Constraints while you do it:
- Research the code before asking me anything; ask at most four questions, only
  about things the code cannot tell you.
- Back up any file you rewrite to .claude/kit/backup/<timestamp>/.
- Keep CLAUDE.md under 150 lines; facts go to knowledge/ nodes, procedures to
  skills, subsystem rules to .claude/rules/ with paths frontmatter.
- Every knowledge node gets a source and dates; inferred facts get confidence medium.
- Run python .claude/kit/kg.py build and validate at the end and fix all errors.
- Do not commit. Report what you wrote, what you verified, and what is still open.
```

## Ongoing session starter

For an agent without hooks, paste this at the start of a session to get the same context the SessionStart hook gives Claude Code:

```
Before we start: read knowledge/index.md and the three newest files in
knowledge/lessons/. If .claude/kit/handoffs/ has a file from the last two weeks,
read the newest one. Then tell me in three lines what you know about the current
state of this project, and wait for the task.
```
