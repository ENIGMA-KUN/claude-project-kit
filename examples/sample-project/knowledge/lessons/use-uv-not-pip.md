---
type: lesson
title: "Use uv, not pip"
description: "pip installs into the global interpreter here; uv manages the project venv and the lock file."
tags: [python, tooling, uv]
status: active
confidence: high
source: "correction, session 2026-11-18"
created: 2026-11-18
updated: 2026-11-18
review_by: 2027-02-16
rule: "Run uv add / uv run; never pip install."
trigger: [pip install, ModuleNotFoundError, site-packages, requirements.txt]
severity: medium
paths: [pyproject.toml]
relations:
  depends_on: [architecture/build-system]
---

## What happened

Claude ran `pip install httpx` to add a dependency. It landed in the global Python, `uv.lock` did not change, and CI failed with `ModuleNotFoundError`.

## Root cause

pip is the default habit for Python projects; nothing in the session said this repo uses uv.

## Prevention

`uv add <pkg>` for dependencies, `uv run <cmd>` for anything that needs the venv. Check `uv.lock` changed in the diff.

## Evidence

Session 2026-11-18, CI run failing on the missing import.
