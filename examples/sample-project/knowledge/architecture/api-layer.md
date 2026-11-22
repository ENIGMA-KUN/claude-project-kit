---
type: architecture
title: "API layer"
description: "FastAPI routers: validate input with Pydantic, call a service, shape the response. No business logic, no database access."
tags: [fastapi, http, routes]
status: active
confidence: high
source: "kit-init scan of app/api/"
created: 2026-10-20
updated: 2026-10-20
review_by: 2026-12-19
paths: ["app/api/**"]
relations:
  depends_on: [architecture/billing-service]
  implements: [decisions/three-layer-architecture]
---

## Responsibility

One router per resource in `app/api/`. Routers parse and validate the request, call exactly one service function, and map service errors to HTTP status codes.

## Boundaries

- Never import from `app/db/` here. See [the lesson](../lessons/never-query-db-from-routes.md).
- Public ids in responses are UUIDs, never database integers.

## Key paths

- `app/api/orders.py`: order endpoints
- `app/api/deps.py`: shared dependencies (auth, session)

## Gotchas

Response models are separate from ORM models on purpose; do not return ORM objects directly.
