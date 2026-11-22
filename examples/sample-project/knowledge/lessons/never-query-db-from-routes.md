---
type: lesson
title: "Never query the database from routes"
description: "Route handlers that import from app/db bypass billing rules and break the layer contract."
tags: [fastapi, layering, sqlalchemy]
status: active
confidence: high
source: "correction, session 2026-10-23 (orders list endpoint)"
created: 2026-10-23
updated: 2026-10-23
review_by: 2027-01-21
rule: "Never import app.db in app/api; add or reuse a service function instead."
trigger: [from app.db, session.execute, select(, app/api]
severity: high
paths: ["app/api/**"]
relations:
  implements: [decisions/three-layer-architecture]
  related: [architecture/api-layer]
---

## What happened

Asked for a filtered orders list, Claude wrote a SQLAlchemy query inside the route handler. It skipped the soft-delete filter the service applies.

## Root cause

The fastest path to a working endpoint ignores the layer rule, and nothing mechanical enforced it.

## Prevention

Add a service function (`orders_service.list_orders(filters)`) and call it from the route. If the same mistake recurs, enforce it with an import-linter contract in CI.

## Evidence

Review comment on PR #41; reverted in commit `3f2a9c1`.
