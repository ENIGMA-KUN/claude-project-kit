---
name: experiment
description: Research-integrity guard for ML and data work. Sets up protected evaluation paths (eval data, test sets, metric code, baselines), fingerprints them, runs experiments through a logger that records seed, commit, data fingerprints and metrics, and produces results tables that include every run. Use when training, evaluating, tuning or benchmarking, and before reporting any number.
argument-hint: "setup | run <name> -- <command> | check | report [name] | trace <metric> <value>"
when_to_use: "Training, evaluation, hyperparameter tuning, benchmarks, ablations, any time a result will be reported."
effort: medium
---

# Experiment integrity

Arguments: `$ARGUMENTS`

Research goes wrong quietly. The usual ways are moving the goalposts (changing the evaluation set, the metric code or a baseline), quietly changing a seed or a hyperparameter between runs, reporting only the best run, and numbers in a summary that no run produced. This skill makes each of those checkable. It applies the same rules whichever model, tool or person does the work.

Commands write `python`; use the interpreter from `.claude/kit/config.json` if it differs.

## setup

1. Find the evaluation surface: held-out and test data, evaluation scripts, metric implementations, baseline configs and checkpoints, fixed prompts or annotation guidelines for LLM evaluation. Look at the code map, configs and the README.
2. Propose a list of globs to the user with AskUserQuestion (multi-select), for example `data/test/**`, `eval/**`, `src/metrics.py`, `configs/baseline.yaml`. Large raw datasets are fine: files over 64 MB are fingerprinted by size and timestamp.
3. Write the approved globs to `research.protected_paths` in `.claude/kit/config.json`. From now on a hook asks the user before anything edits, moves or deletes them.
4. `python .claude/kit/runlog.py baseline` to fingerprint the evaluation as it is now.
5. Record the evaluation protocol as `decision` nodes with `/learn` (split, metric definitions, seeds, number of runs, what counts as an improvement), and add these lines to the project `CLAUDE.md` under "Working loop":

   ```
   - Run experiments through `python .claude/kit/runlog.py run --name <name> -- <command>`; only report numbers that a logged run produced, and report failed runs too.
   - Never edit protected evaluation paths (research.protected_paths) without the user's approval, recorded with /decide.
   ```

6. Suggest committing `.claude/kit/research-baseline.json` and `.claude/kit/runs.jsonl` if collaborators should be able to check results; they are plain JSON.

## run

`python .claude/kit/runlog.py run --name <experiment> [--seed N] [--metrics-file results.json] -- <command>`

- Use a name per experiment family (`baseline`, `lr-sweep`, `ablation-no-aug`) so `report` can group runs.
- Pass the seed explicitly; it is also read from `--seed N` or `seed=N` in the command.
- Metrics are parsed from lines like `accuracy: 0.913` or `f1=0.82`, from a JSON line, or from `--metrics-file`.
- If the run prints a warning that protected files changed, stop and tell the user before doing anything else.

## check

`python .claude/kit/runlog.py check`. Any change since the baseline needs an explanation and the user's approval. If the change was intended (a corrected label file, a fixed metric bug), record it with `/decide` and re-baseline with `runlog.py baseline`; results before and after are then not comparable, and the report must say so.

## report

`python .claude/kit/runlog.py report --name <experiment>` gives a Markdown table of every run, failed ones included. When you summarise results:

- Report all runs of the comparison, or state the selection rule you used before seeing results.
- Compare runs with the same seeds, data fingerprints and evaluation code (`runlog.py compare RUN_A RUN_B`).
- Give baselines the same tuning budget as the new method, or say they did not get it.
- Mark single-seed results as single-seed.

## trace

`python .claude/kit/runlog.py find --metric <name> --value <number>` must find the run behind every number you report. A number with no run behind it is removed from the summary or rerun.

## When something looks wrong

If results look too good, a metric jumps after an unrelated change, or files you did not mean to touch changed, say so plainly and show the evidence (`check`, `compare`, the diff). Do not explain it away. For high-stakes results, offer `/second-opinion` so a different model reviews the change and the run log.
