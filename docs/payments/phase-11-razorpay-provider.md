# Phase 11 — Razorpay Provider

## Scope
Implement `RazorpayProvider`: create Razorpay order, verify payment
signature, fetch payment where necessary, initiate refund, handle
provider errors. Keep it isolated from `OrderService`, `RestaurantService`,
`RiderService`, `AdminService` — those talk through the payment service
abstraction instead.

## Finding
Already fully built in Phase 4/5 (`app/services/payment/razorpay_provider.py`)
— verification only, no code changes.

- **Create order** — `create_order()`, real `POST /v1/orders`.
- **Verify signature** — `verify_payment_signature()`, pure local
  HMAC-SHA256, no network call.
- **Fetch payment** — `fetch_payment()`, real `GET /v1/payments/{id}`.
- **Initiate refund** — `initiate_refund()`, real
  `POST /v1/payments/{id}/refund`.
- **Handle provider errors** — every `httpx.HTTPError` is caught and
  translated into `ProviderRequestError`; missing credentials raise
  `ProviderNotConfiguredError` before any network call is attempted.

**Isolation** — grepped `orders.py`, `restaurants.py`,
`rider_deliveries.py`, every `admin_*.py`: zero references to
`RazorpayProvider` outside `app/services/payment/` and the payments
router itself. Everything else goes through `PaymentService` or a plain
`settings` flag.

## Testing
`test_payment_service_architecture.py` (20) + `test_payment_api.py` (19)
— 39/39 passing.

## Live verification
Called `RazorpayProvider` directly against the real
`https://api.razorpay.com/v1` (using the keys in `rzp-test-key.csv`):
`create_order` returned a genuine order id with correct amount round-trip;
`verify_payment_signature` accepted a genuine HMAC and rejected a forged
one; `fetch_payment` and `initiate_refund` — never previously exercised
against the real API, only `httpx.MockTransport` — each made a real
network call against a nonexistent payment id and correctly translated
Razorpay's real error response into `ProviderRequestError`; an
unconfigured provider raised `ProviderNotConfiguredError` without any
network call. 8/8 checks passed.
