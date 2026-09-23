# Phase 8 — COD Collection

## Scope
At delivery: rider collects COD, records the collection. The rider must
not be able to arbitrarily change the expected COD amount, order total,
or payment amount — the backend calculates the expected collection.

## Finding
Already fully built (pre-existing Phase 16/26/28 work) — verification
only, no code changes.

`collect_cod_payment()` (`app/services/rider_deliveries.py`), mounted at
`POST /api/v1/rider/deliveries/{id}/cod-collect`, takes **no request
body at all** — order, rider, and amount are all resolved server-side.
`payment.amount = order.total`, re-read fresh from the database at the
moment of collection. Guarded so collection is only possible while the
order is `OUT_FOR_DELIVERY`, and `complete_delivery()` refuses to move a
COD order to `DELIVERED` until collection has actually happened.
Race-safe (`IntegrityError`-recover on concurrent first-collect calls)
and idempotent (a same-rider retry returns the original record).

## Testing
`test_cod_end_to_end.py::test_no_client_can_manipulate_the_cod_amount` —
an existing adversarial test sending a spoofed `amount`/`total`/
`cod_amount`/`payment_amount` payload at every step of the rider flow
(accept/pickup/collect/complete); proves the recorded amount is always
`order.total`.

## Live verification
Sent a tampered collection request (`amount: "1.00"`,
`payment_amount: "999999.00"`) against the real dev server — ignored
entirely; the real order total was recorded.
