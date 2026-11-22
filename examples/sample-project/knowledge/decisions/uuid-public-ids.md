---
type: decision
title: "UUIDs as public ids"
description: "APIs expose a public_id UUID, never the integer primary key."
tags: [api, ids, security, uuid]
status: active
confidence: high
source: "user, during kit-init interview"
created: 2026-10-20
updated: 2026-10-20
review_by: 2027-04-18
relations:
  related: [architecture/api-layer]
---

## Context

Sequential integer ids in URLs leaked order volume to competitors and made enumeration trivial.

## Decision

Every table has `public_id UUID NOT NULL UNIQUE`. Routes, responses and logs use it; integer ids stay internal.

## Alternatives rejected

- UUID primary keys: index bloat on the largest tables.
- Hashids: reversible with enough samples.

## Consequences

Lookups by public id need the unique index; repositories expose `get_by_public_id`.
