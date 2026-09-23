# Payment System & Razorpay Integration — Phase Log

This directory documents every phase of the Payment System & Razorpay
Integration protocol, a production-oriented payment architecture (COD +
Razorpay) built inside the existing Say Hi Chai backend. Each phase has its
own file below, written at the time that phase was completed.

Standing architectural rules that hold across every phase:

- No separate payment backend, database, or auth mechanism — payments live
  inside the existing FastAPI backend and Postgres database, behind the
  existing single JWT auth.
- All payment logic goes through `PaymentService` → `PaymentProvider` →
  `RazorpayProvider` → Razorpay. No other service (`OrderService`,
  `RestaurantService`, `RiderService`, `AdminService`) talks to
  `RazorpayProvider` directly.
- The backend is the sole authority for every payment-related value — order
  amount, payment status, provider ids. A client-supplied amount is never
  trusted, anywhere.
- Money is always `Decimal`/`Numeric(10,2)`, never float.
- Never fabricate a successful payment — if a provider isn't configured or
  a signature can't be verified, the honest answer is an error, not a fake
  success.

| Phase | Title | Status |
|---|---|---|
| 1 | [Payment System Audit](phase-1-gap-report.md) | Complete — audit only |
| 2 | [Payment Domain Model](phase-2-payment-domain-model.md) | Complete |
| 3 | [Database Migrations](phase-3-database-migrations.md) | Complete |
| 4 | [Payment Service Architecture](phase-4-payment-service-architecture.md) | Complete |
| 5 | [Payment API Design](phase-5-payment-api-design.md) | Complete |
| 6 | [Checkout Payment Decision](phase-6-checkout-payment-decision.md) | Complete |
| 7 | [COD Payment Architecture](phase-7-cod-payment-architecture.md) | Complete — verification only |
| 8 | [COD Collection](phase-8-cod-collection.md) | Complete — verification only |
| 9 | [COD Settlement](phase-9-cod-settlement.md) | Complete — verification only |
| 10 | — | Not yet requested |
| 11 | [Razorpay Provider](phase-11-razorpay-provider.md) | Complete — verification only |
| 12 | [Razorpay Order Creation](phase-12-razorpay-order-creation.md) | Complete |
| 13 | [Customer Mobile Razorpay Checkout](phase-13-customer-mobile-razorpay-checkout.md) | Complete |
| 14 | [Payment Signature Verification](phase-14-payment-signature-verification.md) | Complete |
| 15 | [Payment Amount Validation](phase-15-payment-amount-validation.md) | Complete |
| 16 | [Payment Status Synchronization](phase-16-payment-status-synchronization.md) | Complete |
| 17 | [Payment Webhooks](phase-17-payment-webhooks.md) | Complete |
| 18 | [Webhook Idempotency](phase-18-webhook-idempotency.md) | Complete |
| 19 | [Payment Failure Handling](phase-19-payment-failure-handling.md) | Complete |
| 20 | [Payment Retry](phase-20-payment-retry.md) | Complete |
| 21 | [Idempotent Order Payment Creation](phase-21-idempotent-order-payment-creation.md) | Complete |
| 22 | [Payment/Order State Machine](phase-22-payment-order-state-machine.md) | Complete |
| 23 | [Refund Architecture](phase-23-refund-architecture.md) | Complete |
| 24 | [Razorpay Refund](phase-24-razorpay-refund.md) | Complete |
| 25 | [Partial Refunds](phase-25-partial-refunds.md) | Complete |
| 26 | [Customer Payment History](phase-26-customer-payment-history.md) | Complete |
| 27 | [Admin Payment Management](phase-27-admin-payment-management.md) | Complete |
| 28 | [Restaurant Payment Visibility](phase-28-restaurant-payment-visibility.md) | Complete |
| 29 | [Rider Payment/COD Visibility](phase-29-rider-payment-cod-visibility.md) | Complete |
| 30 | [Financial Ledger Validation](phase-30-financial-ledger-validation.md) | Complete |
| 31 | [Security Audit](phase-31-security-audit.md) | Complete |
| 32 | [Payment Failure & Recovery Testing](phase-32-payment-failure-recovery-testing.md) | Complete |
| 33 | [Complete COD E2E Test](phase-33-complete-cod-e2e-test.md) | Complete |
| 34 | [Complete Razorpay E2E Test](phase-34-complete-razorpay-e2e-test.md) | Complete |
| 35 | [Duplicate Payment Test](phase-35-duplicate-payment-test.md) | Complete |
| 36 | [Refund E2E Test](phase-36-refund-e2e-test.md) | Complete |
| 37 | [API & Frontend Validation](phase-37-api-frontend-validation.md) | Complete |
| 38 | [Automated Tests](phase-38-automated-tests.md) | Complete |
| 39 | [Performance & Reliability](phase-39-performance-reliability.md) | Complete |
| 40 | [Production Payment Readiness](phase-40-production-payment-readiness.md) | Complete — critical finding, action still needed (see doc) |

Phase 10 was skipped by explicit user instruction (jumped straight from
Phase 9 to Phase 11); it remains open if a Phase 10 is specified later.
Phase 25 was likewise skipped initially (jumped from Phase 24 to Phase
26) but was later specified and completed out of numeric order, after
Phase 32.

Phase 13 downgraded `customer-mobile` from Expo SDK 57 to SDK 54 (React
Native 0.86 → 0.81, Legacy Architecture) to use the native
`react-native-razorpay` SDK — see that phase's doc for the full rationale
and tradeoffs the user was presented with before choosing this path.
