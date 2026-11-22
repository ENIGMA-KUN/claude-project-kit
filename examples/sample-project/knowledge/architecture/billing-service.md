---
type: architecture
title: "Billing service"
description: "Business rules for invoices, proration and refunds. Pure functions over repository calls; the only place money is computed."
tags: [billing, invoices, money]
status: active
confidence: high
source: "kit-init scan of app/services/"
created: 2026-10-20
updated: 2026-11-04
review_by: 2026-12-19
paths: [app/services/billing.py]
relations:
  depends_on: [architecture/database-layer]
  implements: [decisions/three-layer-architecture]
  related: [concepts/active-customer]
---

## Responsibility

Compute invoices and refunds. All amounts are integer cents; rounding happens once, at invoice finalisation.

## Boundaries

- Talks to the database only through repository functions in `app/db/`.
- Never calls the payment provider directly; that goes through `app/integrations/payments.py`.

## Gotchas

`monthly_invoice` bills only active customers. "Active" has a specific meaning here: see [Active customer](../concepts/active-customer.md).
