---
type: decision
title: "Three-layer architecture"
description: "Routes call services, services call repositories. Each layer only talks to the one below it."
tags: [architecture, layering, fastapi]
status: active
confidence: high
source: "docs/adr/0002-layers.md, confirmed by the user during kit-init"
created: 2026-10-20
updated: 2026-10-20
review_by: 2027-04-18
relations:
  related: [architecture/api-layer, architecture/billing-service, architecture/database-layer]
---

## Context

Early versions had SQL in route handlers. Billing bugs were hard to test because rules were spread across endpoints.

## Decision

Three layers: `app/api` (HTTP), `app/services` (rules), `app/db` (persistence). A layer imports only from the layer below.

## Alternatives rejected

- Fat routes: fastest to write, impossible to unit test billing.
- A full hexagonal setup with ports and adapters: too much ceremony for a two-person team.

## Consequences

Service functions are unit tested without HTTP or a database. Adding an endpoint touches three folders.
