# `retail_v2` temporal identity

There are two canonical temporal classes.

## Cumulative/versioned

Only `sales`, `sales_adjustments` and `sales_fulfillments` carry explicit positive,
monotonic integer version columns.

- `sales` is unique by
  `(sku_id, store_id, channel_id, date, sales_version)`.
- `sales_adjustments` is unique by
  `(adjustment_id, adjustment_version)`.
- `sales_fulfillments` is unique by
  `(fulfillment_line_id, fulfillment_version)`.

At a cutoff, select the greatest `(known_as_of, version)` not later than the
cutoff. Never sum availability versions of the same fact. `known_as_of` cannot
decrease as version increases.

## Observational/reference

All other temporal canonical facts use their stable natural/effective key plus
`known_as_of`. The word `version` does not appear in their grain unless an
explicit version field exists. Exact duplicate complete keys are idempotent;
divergent payloads at one complete key quarantine.

Every temporal row carries both `known_as_of` and
`known_as_of_evidence_grade`. `known_as_of` is availability evidence, not
business time:

- accepted evidence: native observation, native processing, explicitly proven
  posting availability, native extract observation, or marked landing backfill;
- business/effective dates such as `sale_date`, `event_date`, `effective_from`
  and `receipt_date` do not become availability time by default;
- `landing_backfill` cannot support historically point-in-time capabilities and
  produces a capability downgrade rather than a silent pass.

For fulfilled sales, the order date remains the business date while fulfilment
creation/processing supplies availability evidence. Processed returns and
successful refund transactions append later adjustment versions.
