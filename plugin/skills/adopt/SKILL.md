---
name: adopt
description: Install the Claude project kit into the current repository (or upgrade it) and adapt it to the code. Use when the user asks to set up, add, adopt or upgrade the project kit, the self-improving setup, the knowledge graph or the task ledger in this project.
argument-hint: "[--refresh] [--new]"
disable-model-invocation: true
---

# Adopt the project kit here

The kit's installer ships with this plugin at `${CLAUDE_SKILL_DIR}/../../../install.py`.

1. Find the project root: `git rev-parse --show-toplevel`, or the current working directory outside git. If it looks wrong (a home folder, a system folder, the plugin cache itself), ask the user which folder to use.
2. Find a Python 3.8+ interpreter: try `python --version`, then `python3 --version`, then `py -3 --version`. If none works, tell the user to install Python from https://www.python.org/downloads/ and stop.
3. Run the installer and show its summary to the user:

   ```
   <python> "${CLAUDE_SKILL_DIR}/../../../install.py" "<project root>" --python-cmd "<python command that worked>"
   ```

   It never overwrites the user's files: existing `CLAUDE.md`, `.claude/settings.json` and `.claude/constitution.md` are kept, and the kit's versions go to `.claude/kit/incoming/`.
4. Read `<project root>/.claude/skills/kit-init/SKILL.md` and follow it with these arguments: `$ARGUMENTS`. If the installer reported an upgrade, add `--refresh`.
5. When `/kit-init` is done, tell the user to restart Claude Code in this folder so the project hooks and skills load, and that from then on the day-to-day commands are `/learn`, `/reflect`, `/decide`, `/curate` and `/handoff`.
