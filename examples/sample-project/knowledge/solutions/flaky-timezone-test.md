---
type: solution
title: "Flaky invoice test around daylight saving"
description: "test_monthly_invoice failed once a year; naive datetimes shifted the billing period by an hour."
tags: [tests, flaky, datetime, timezone, billing]
status: active
confidence: high
source: "debugging session 2026-11-02, commit 9b1e4d0"
created: 2026-11-02
updated: 2026-11-02
review_by: 2027-03-02
paths: [tests/test_billing.py, app/services/billing.py]
relations:
  fixes: [lessons/store-timestamps-in-utc]
---

## Problem

`test_monthly_invoice` passed for months, then failed on 2026-10-25 with an invoice one hour short.

## Solution

1. Reproduce by freezing time at `2026-10-25T01:30` Europe/Paris with `time-machine`.
2. Replace `datetime.now()` with `datetime.now(timezone.utc)` in the service.
3. Migrate `invoices.period_start` and `period_end` to `timestamptz`.

## Why it works

UTC has no daylight saving jumps, so period arithmetic is exact.

## Edge cases

Customer-facing PDFs still show local time; convert at render time with the customer's zone.
