---
type: architecture
title: "Database layer"
description: "SQLAlchemy models and repository functions over PostgreSQL; migrations with Alembic."
tags: [postgres, sqlalchemy, alembic, migrations]
status: active
confidence: high
source: "kit-init scan of app/db/"
created: 2026-10-20
updated: 2026-10-20
review_by: 2026-12-19
paths: ["app/db/**"]
relations:
  implements: [decisions/three-layer-architecture]
---

## Responsibility

Models in `app/db/models.py`, one repository module per aggregate. Repositories return plain dataclasses, not ORM objects.

## Gotchas

- Generate migrations with `uv run alembic revision --autogenerate` against the local dev database only.
- Every table has both an integer primary key and a `public_id` UUID column.
