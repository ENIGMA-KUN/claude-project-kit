---
type: architecture
title: "Build system and tooling"
description: "uv manages Python, the venv and dependencies; ruff lints; pytest runs tests."
tags: [uv, tooling, python, ruff, pytest]
status: active
confidence: high
source: "kit-init scan of pyproject.toml"
created: 2026-10-20
updated: 2026-10-20
review_by: 2026-12-19
paths: [pyproject.toml]
relations:
  related: []
---

## Responsibility

`pyproject.toml` is the single source for dependencies. `uv.lock` is committed.

## Key commands

- `uv sync`: create or update the venv
- `uv run pytest -q`: tests
- `uv run ruff check .`: lint
