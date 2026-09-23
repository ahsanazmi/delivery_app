# Phase 4 — Payment Service Architecture

## Scope
Build a payment service layer so the rest of the application interacts
with `PaymentService` rather than calling Razorpay directly from route
handlers:

```
API -> PaymentService -> PaymentProvider -> RazorpayProvider -> Razorpay
```

## What was built
The full `backend/app/services/payment/` package:

- **`provider.py`** — `PaymentProvider` (ABC) with five abstract methods
  (`create_order`, `verify_payment_signature`, `fetch_payment`,
  `initiate_refund`, `verify_webhook_signature`) and three frozen,
  provider-agnostic dataclasses: `ProviderOrder`, `ProviderPayment`,
  `ProviderRefund`.
- **`razorpay_provider.py`** — the concrete `RazorpayProvider`, making real
  `httpx` calls to `https://api.razorpay.com/v1`. Amounts are converted to
  paise (`_to_minor_units`/`_from_minor_units`, `ROUND_HALF_UP`).
  Credentials (`key_id`/`key_secret`/`webhook_secret`) are lazy
  properties reading `settings.*` fresh on every access unless an explicit
  override was passed to `__init__` — so one long-lived
  `RazorpayProvider()` instance still sees a later-changed setting (a test
  monkeypatch, or a real config reload).
- **`verification.py`** — `verify_hmac_signature(payload, signature,
  secret)`, using `hmac.compare_digest`.
- **`exceptions.py`** — plain-Python exceptions with no FastAPI
  dependency: `PaymentError`, `ProviderNotConfiguredError`,
  `ProviderRequestError`, `PaymentVerificationError`, `RefundError`.
- **`refund_service.py`** — `create_refund()`: validates the payment is in
  `(PAID, PARTIALLY_REFUNDED)`, validates the amount against what's
  already refunded, records a `Refund` row, calls the provider only for
  online payments (COD marks `COMPLETED` immediately — no gateway to
  call).
- **`payment_service.py`** — the single facade:
  `create_payment_for_order`, `verify_payment`, `refund`,
  `get_payment_for_order` (`retry_payment` added in Phase 5).

## Testing
`tests/test_payment_service_architecture.py` — `RazorpayProvider` tested
via `httpx.MockTransport` (no real network); a separate in-memory
`FakeProvider(PaymentProvider)` test double used to test
`PaymentService`/`RefundService` orchestration without HTTP at all.

## Result
Purely additive — nothing in this phase was wired into any existing
endpoint yet (that happened in Phase 5).
