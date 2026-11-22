---
type: concept
title: "Active customer"
description: "A customer with a paid or trialing subscription on the first day of the billing period. Paused accounts are not active."
tags: [billing, domain, metrics]
status: active
confidence: high
source: "user, during kit-init interview"
created: 2026-10-20
updated: 2026-10-20
review_by: 2027-04-18
relations:
  related: [architecture/billing-service]
---

## Definition

`status IN ('paid', 'trialing')` on the first day of the period, evaluated in UTC. A customer who pauses mid-month is still active for that month.

## Where it appears

- `billing.monthly_invoice` selects active customers.
- The "active customers" dashboard metric uses the same rule; keep them in sync.
