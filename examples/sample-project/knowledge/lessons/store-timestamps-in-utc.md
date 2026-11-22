---
type: lesson
title: "Store timestamps in UTC"
description: "Naive local datetimes broke invoice periods around daylight saving changes."
tags: [datetime, timezone, billing, tests]
status: active
confidence: high
source: "debugging session 2026-11-02"
created: 2026-11-02
updated: 2026-11-02
review_by: 2027-01-31
rule: "Use datetime.now(timezone.utc) and timestamptz columns; never naive datetimes."
trigger: [datetime.now(), utcnow, naive datetime, timezone, DST, flaky]
severity: high
paths: [app/services/billing.py]
relations:
  related: [architecture/billing-service, solutions/flaky-timezone-test]
---

## What happened

An invoice test failed only on the last Sunday of October.

## Root cause

`datetime.now()` returned local time; the period boundary moved by an hour at the DST switch.

## Prevention

Aware UTC datetimes everywhere; convert to local time only for display.

## Evidence

See the solution node for the full investigation.
