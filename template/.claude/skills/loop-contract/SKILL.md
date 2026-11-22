---
name: loop-contract
description: Write and run a bounded loop contract before multi-step, risky or unattended work. Fixes the goal, allowed actions, verification commands, attempt budget, stop rules and escalation path, picks the smallest control structure (single loop or explicit graph), and accepts the result only with evidence and an independent verifier.
argument-hint: "<task description>"
disable-model-invocation: true
effort: high
---

# Bounded loop contract

Task: `$ARGUMENTS`

"Keep going until it works" has no stop rule, no budget and no acceptance test. A contract makes each of those explicit and checkable. Write it before acting, follow it while acting, and accept the result only on evidence.

## 1. Choose the smallest structure

| The task needs... | Use |
|-------------------|-----|
| One bounded change where every failed check leads to one next action | Single loop (section 2 only) |
| Known branches, parallel parts with a join, human checkpoints mid-way, or recovery across sessions | Explicit graph (sections 2 and 3) |

Do not build a graph for a task a loop can do. Every extra node adds state and failure modes.

## 2. Write the loop contract

Read `.claude/kit/config.json` for verification commands and `loop.max_attempts`. Query the knowledge graph for lessons on the touched area (`python .claude/kit/kg.py query "<area terms>" --type lesson`). Then create `.claude/kit/contracts/<YYYY-MM-DD>-<slug>.md`:

```markdown
# Contract: <task>

| Field | Value |
|-------|-------|
| Goal and input | <requirement in one or two sentences; base revision: <git rev-parse --short HEAD>> |
| Acceptance criteria | <numbered, each checkable> |
| State outside the context | this file; <branch or worktree>; <other files> |
| Allowed actions | <files and folders that may change; commands allowed; anything forbidden> |
| Observation | <which outputs feed the next attempt: test output, typecheck, logs> |
| Verification | <exact commands, for example `pytest -q tests/x`; expected exit status 0> |
| Budget | <max attempts, default 3>; same failure 3 times ends the loop |
| Stop: success | all criteria met, verification passes, verifier agent returns ACCEPT |
| Stop: failure | budget spent, or a forbidden action would be needed |
| Escalate to user | ambiguous requirement, irreversible effect, verifier says ESCALATE, budget spent |
| Relevant knowledge | <node ids from the query> |

## Run log
| # | Action | Verification result | Next |
|---|--------|---------------------|------|
```

Show the contract to the user and get a yes before starting if the task is risky, long or touches shared systems.

## 3. Graph contract (only if section 1 chose a graph)

Add a YAML block that a reviewer can check without running anything:

Example: a feature with a backend and a frontend part built in parallel.

```yaml
graph: add-export-feature
version: 1
state:                                   # one writer per field
  spec:          { writer: user, frozen_after: plan }
  api_branch:    { writer: build_api }
  ui_branch:     { writer: build_ui }
  check_report:  { writer: check }       # command, exit status, failing tests
  attempts_left: { writer: route_failure, start: 2, floor: 0 }
nodes:
  plan:          { produces: task_list, needs_user_ok: true }
  build_api:     { worktree: wt-api, allowed: ["src/api/**", "tests/api/**"] }
  build_ui:      { worktree: wt-ui,  allowed: ["src/web/**", "tests/web/**"] }
  join:          { waits_for: [build_api, build_ui], timeout: 2h, on_missing: escalated }
  check:         { runs: config.verify.test, then: config.verify.lint }
  route_failure: { decrements: attempts_left }
  accept:        { agent: verifier, verdicts: [ACCEPT, REJECT, ESCALATE] }
edges:
  - plan -> build_api, build_ui     # fan out after the user approves the task list
  - build_api, build_ui -> join
  - join -> check
  - check -> accept                 # when every command exits 0
  - check -> route_failure          # when any command fails
  - route_failure -> build_api      # failing tests under tests/api, attempts_left > 0
  - route_failure -> build_ui       # failing tests under tests/web, attempts_left > 0
  - route_failure -> stopped        # attempts_left == 0
  - accept -> shipped               # ACCEPT with an evidence table
  - accept -> route_failure         # REJECT
  - accept -> escalated             # ESCALATE
terminals: [shipped, stopped, escalated]   # only the user turns stopped or escalated into new work
```

Rules: only one writer per state field; one node owns the budget counter; no edge reaches `shipped` without passing `check` and the verifier; every node has a way to end, including a timeout on joins. A valid route does not prove a correct result, so acceptance still needs evidence. Parallel branches get separate worktrees and an explicit join.

## 4. Execute

- One attempt at a time. After each attempt run the verification commands and append a row to the run log with the actual exit status.
- If the hook reports the same failure three times, the loop is over: stop and escalate with what you learned.
- Do not widen scope beyond "Allowed actions". If the task needs it, stop and ask.
- If context is compacted mid-task, re-read the contract before continuing.

## 5. Accept

When verification passes, start the `verifier` agent with: the requirement and acceptance criteria, the base revision, and the verification commands. It reviews the diff with fresh context and returns ACCEPT, REJECT or ESCALATE with evidence. A REJECT counts as a failed attempt against the budget.

Report to the user: terminal state (done, failed, escalated), the evidence table (criterion, command, exit status), the verifier verdict, and anything learned. Offer `/learn` for any lesson that would have saved an attempt.
