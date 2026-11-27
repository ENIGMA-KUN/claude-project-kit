---
name: second-opinion
description: Ask a different model (Codex CLI, Gemini CLI, Claude with another model, or a local model) to review the current change independently, and record its verdict. Use for high-stakes changes, research results, or when the user wants a check that does not share this model's blind spots.
argument-hint: "[requirement or path to a loop contract]"
disable-model-invocation: true
effort: low
---

# Second opinion

Arguments: `$ARGUMENTS`

The `verifier` agent runs on the same model that wrote the change, so it can share that model's blind spots. This skill sends a review packet to a different model through a command-line tool the user configured, and treats its verdict as one more piece of evidence, not as the final word.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## 1. Is it set up?

Read `second_opinion` in `.claude/kit/config.json`. If `enabled` is false or `command` is empty, tell the user it is off and how to turn it on, and stop. Do not enable it yourself; it sends code to another provider, which is the user's decision (constitution C13). Example commands, to be checked against the tool's own `--help`:

| Tool | command | how it reads the packet |
|------|---------|-------------------------|
| Codex CLI | `codex exec -` | stdin |
| Gemini CLI | `gemini -p "Review the change described in the input and answer in the format it asks for."` | stdin is appended to the prompt |
| Claude, another model | `claude -p --model opus` | stdin |
| Any tool that needs a file | `mytool --input {prompt_file}` | the packet file |

## 2. Show what will be sent

`python .claude/kit/review.py --requirement "<requirement>" --dry-run` (or `--requirement-file .claude/kit/contracts/<contract>.md`). Tell the user the packet size and the command it would go to. The packet holds the requirement, the diff (files such as `.env`, keys and `secrets/` are left out), the task ledger's goal, decisions and dead ends, and the research run log when research paths are protected. The whole packet is scanned for secrets, and any hit stops it.

## 3. Run it

`python .claude/kit/review.py --requirement "<requirement>" [--base <revision>] [--evidence-file <test output>]`

## 4. Use the verdict

- ACCEPT: report it alongside the verifier's verdict.
- REJECT: treat it as a failed check. Read the reasons, check each one against the code, fix real defects, and say which reasons you think are wrong and why. Never dismiss a REJECT without showing evidence.
- ESCALATE or no verdict: hand the decision to the user with both reviews.
- When the verifier and the second opinion disagree, show both to the user; do not pick the one you prefer.

The full packet and the reviewer's answer are saved in `.claude/kit/reviews/` (gitignored).
