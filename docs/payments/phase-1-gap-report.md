# PHASE 1 — PAYMENT SYSTEM AUDIT: GAP REPORT

No code was changed in this phase — this is a read-only inspection of `backend/`, `customer-mobile/`, `rider-mobile/`, `business-web/`, and `admin-web/` (the master command's tree names `business-web` as containing both the Restaurant Owner and Admin portals; in reality the Admin Portal is a separate app, `admin-web` — see "Structural correction" below).

## What already exists

### Models
- **`Order`** (`app/models/order.py`) — `payment_method: str` (default `"cod"`), `payment_status: str` (default `"pending"`, **plain string, not an enum**), `is_paid: bool`, `subtotal`/`delivery_fee`/`tax`/`discount`/`total` (all `Numeric(10,2)`, all with non-negative `CheckConstraint`s), `commission_type`/`commission_rate`/`commission_amount` (snapshotted once at order-creation time, never recomputed).
- **`Payment`** (`app/models/payment.py`) — one row per order (`UniqueConstraint("order_id")`), `provider` (`PaymentProvider` enum: `RAZORPAY` | `COD`), `payment_status` (`PaymentStatus` enum: `PENDING` | `PAID` | `FAILED` | `REFUND_PENDING` | `REFUNDED`), `amount` (`CheckConstraint >= 0`), `razorpay_order_id`/`razorpay_payment_id`/`razorpay_signature`, `is_verified`, `failure_reason`, `refund_id`/`refund_status` (both loose strings, not a real refund model), `collected_by_rider_id`/`collected_at` (COD audit trail).
- **`OrderItem`** — per-line snapshot of `product_name`/`unit_price`/`quantity` at order time, immune to later product/price changes.
- **`Cart`/`CartItem`** — `sync_cart_with_catalog()` refreshes cached name/price from the live `Product` on every read and drops items whose product is no longer active/available.
- **`CommissionRule`** — platform-default (`restaurant_id IS NULL`) or restaurant-specific override, `PERCENTAGE` or `FIXED`. `compute_effective_commission()` resolves and snapshots it once at order-creation time; never re-reads it for a historical order.
- **`RiderEarning`** — append-only ledger, `DELIVERY_FEE` rows auto-credited on delivery completion; `INCENTIVE`/`BONUS`/`ADJUSTMENT` types exist in the enum but nothing writes them yet.
- **`RiderSettlement`** — append-only ledger of real money moving between platform and rider (`PAYOUT`, `REMITTANCE`), `CheckConstraint(amount >= 0)`.

### Services
- **`app/services/checkout.py`** — `validate_checkout()`/`get_checkout_preview()` compute subtotal/delivery_fee/tax/discount/total server-side from the cart, never from client input; block on inactive/closed restaurant, below-minimum order, unserviceable address, maintenance mode.
- **`app/services/commissions.py`** — `compute_effective_commission()`, restaurant-override-then-platform-default resolution.
- **`app/services/payments.py`** — `create_payment_record()`, `verify_payment()` (Razorpay HMAC-SHA256 signature check, honestly refuses with 503 rather than fabricating success when `RAZORPAY_KEY_SECRET` is unset), `refund_payment()`, `record_order_payment()` (the customer-facing, order-derived path), `list_payment_methods()`.
- **`app/services/rider_deliveries.py`** — `collect_cod_payment()`: amount always re-read from `order.total`, never from the request; idempotent retry-safe; a Phase 24 fix already closes the concurrent-double-settlement race with a `SELECT ... FOR UPDATE` lock in the related `admin_settle_cod()`.
- **`app/services/rider_earnings.py`** — `record_delivery_fee_earning()`, credited exactly once per delivered order.
- **`app/services/admin_cod.py`** — `admin_settle_cod()`, `list_admin_cod_reconciliation()`, `get_admin_cod_reconciliation_detail()` — outstanding = collected − remitted, always derived fresh, never a cached balance.
- **`app/services/admin_payments.py`** — `list_admin_payments()`/`get_admin_payment_detail()`, paginated, filterable by method/status/date/search.
- **`app/services/admin_reports.py`** — `_order_financials()`: revenue/commission/restaurant-earnings over `DELIVERED` orders, `restaurant_earnings = subtotal − commission` (deliberately never derived from `total`, since `delivery_fee` belongs to the rider, not the restaurant).

### APIs
- `POST /api/v1/customer/orders/{id}/payment` — the real path (see "what's actually used" below).
- `GET /api/v1/customer/payment-methods`.
- `POST /api/v1/rider/deliveries/{id}/cod-collect`, `POST /api/v1/rider/deliveries/{id}/complete`.
- `POST /api/v1/admin/cod/{rider_id}/settle`, `GET /api/v1/admin/cod`.
- `GET /api/v1/admin/payments`, `GET /api/v1/admin/payments/{id}`.
- `POST /api/v1/payments`, `POST /api/v1/payments/verify`, `POST /api/v1/payments/webhook`, `POST /api/v1/payments/{id}/refund` — generic, provider-agnostic-looking endpoints (see Conflicts below — these are **not actually used by the real app**).

### Frontend
- **`customer-mobile`** — `paymentsApi.ts` calls `GET /customer/payment-methods` and `POST /customer/orders/{id}/payment` only. Checkout only ever sends `payment_method: "cod"` (`CustomerOrderCreate.payment_method: Literal["cod"]` at the schema level — online isn't reachable from this client today).
- **`rider-mobile`** — `deliveriesApi.ts` calls `cod-collect`; its own `payment_status` TypeScript union already matches the backend's 5-value enum exactly (`"pending" | "paid" | "failed" | "refund_pending" | "refunded"`).
- **`business-web`** (Restaurant Owner Portal) — no payment-specific pages; `Orders`/`OrderDetails` display `payment_method`/`payment_status` read-only.
- **`admin-web`** (Admin Portal — a separate app, not inside `business-web`; see below) — `Payments.tsx` (paginated list, search/filter by method/status/date) and `PaymentDetails.tsx` (single payment view, displays `refund_status` but has **no refund action** — nothing in the admin UI can actually initiate a refund).

### Environment variables
`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` all exist in `Settings` and `.env.example` (all currently unset on this dev environment — online payments are honestly disabled, not broken).

### Migrations
Clean, linear history for every payment-adjacent table: `20260907_01` (payments/reviews/coupons), `20260910_06` (coupon eligibility), `20260914_20` (COD collection fields on payments), `20260915_22`/`_23` (rider earnings/settlements), `20260921_32` (commission rules), `20260925_36` (unique constraint on `payments.order_id`), plus the Phase 23 non-negative `CheckConstraint`s. `alembic current` matches head; the one open item (redundant, not missing, uniqueness constraints on unrelated tables) was already reported in the Phase 31 validation report and is not payment-related.

## What can be reused as-is

- `Order`'s money fields and their non-negative constraints.
- `Payment`'s core shape (`order_id` uniqueness, `amount`/`currency`, Razorpay identifier fields, `collected_by_rider_id` audit trail).
- `CommissionRule` + `compute_effective_commission()` — snapshot-at-order-time design is exactly right and shouldn't change.
- `RiderEarning`/`RiderSettlement` ledger design (append-only, never mutated).
- `checkout.py`'s server-side total computation — the backend already never trusts a client-supplied amount.
- `collect_cod_payment()` and `admin_settle_cod()` — both already correct and concurrency-safe (Phase 24).
- `verify_signature()` (HMAC-SHA256) — reusable as the core primitive inside a future `RazorpayProvider`.
- The admin payments list/detail UI and its backend service — solid foundation, just needs a refund action wired in once refunds are real.

## What is incomplete

1. **No `PaymentAttempt` model.** There is currently no record of a *failed or retried* attempt distinct from the single `Payment` row itself — a payment that fails and is retried just mutates the same row's `failure_reason`/`payment_status` in place, with no history of prior attempts.
2. **No `Refund` model.** `refund_id`/`refund_status` are two loose string columns on `Payment` — there's no way to represent a partial refund, multiple refund attempts, or a refund's own timeline independent of the payment it came from.
3. **No real Razorpay order creation.** `POST /payments` sets `razorpay_order_id = f"order_{payment.id}"` — a locally-fabricated string, not a real ID returned by Razorpay's Orders API. There is no outbound HTTP call to Razorpay anywhere in the codebase yet.
4. **The webhook endpoint verifies signatures only.** `POST /payments/webhook`'s own docstring says it plainly: "No order/payment mutation is wired up yet." A genuine payment-captured/failed event from Razorpay today would be authenticated and then silently discarded.
5. **The admin-initiated refund flow doesn't exist.** `PaymentDetails.tsx` can *display* `refund_status` but has no button, and there's no admin-facing refund endpoint at all — only the customer-facing one (see Conflicts, #2).
6. **`RiderEarning`'s `INCENTIVE`/`BONUS`/`ADJUSTMENT` types are defined but nothing ever writes them** — the ledger's shape anticipated this, no phase has built it yet.

## What conflicts with the new payment architecture

1. **Two parallel, inconsistent payment-creation code paths.** `record_order_payment()` (via `POST /customer/orders/{id}/payment`) is the one the real customer-mobile app actually calls — it derives everything from the order itself and rejects anything but COD (501). `create_payment()` (via the generic `POST /payments`) is a *separate* implementation that lets the client's request body set `provider` directly (`PaymentCreate.provider: PaymentProvider = PaymentProvider.RAZORPAY`) and fabricates a fake Razorpay order id. **This second path is not called by any of the four frontends today** — confirmed by grepping every app's API-call sites — but it is live, reachable, and lets a caller pick their own payment provider, which directly contradicts this protocol's own Payment Principle ("the backend determines... which payment provider should be used," never the client). This needs to be resolved (most likely: retired in favor of one path built on the new `PaymentProvider` abstraction) rather than left as dead-but-reachable code once online payments are actually built out.
2. **The customer-facing refund endpoint (`POST /payments/{id}/refund`) is essentially unguarded.** Any authenticated customer can call it for their own payment at any time — no check that the payment is actually `PAID`, no check on the order's state, no admin approval step, and no actual call to Razorpay's refund API. It also leaves `Payment.payment_status = REFUND_PENDING` while simultaneously setting `Order.payment_status = "refunded"` in the same call — the order looks fully refunded while the payment record says only "pending." This is inconsistent even on its own terms, not just incomplete.
3. **`Order.payment_status` is a plain `String(32)`, while `Payment.payment_status` is a proper Postgres enum.** They're meant to mirror each other but nothing enforces that they actually can — a typo'd string on the `Order` side would silently diverge with no database-level protection, unlike `Payment.payment_status`.
4. **The existing `PaymentStatus` enum doesn't cover the master command's suggested state list.** Current: `PENDING, PAID, FAILED, REFUND_PENDING, REFUNDED`. Missing from the suggested list: `PROCESSING`, `CANCELLED`, `PARTIALLY_REFUNDED`. Notably, **`admin-web`'s own `AdminPaymentStatusValue` TypeScript type already includes `"CANCELLED"`** as a filter option — meaning the frontend already anticipated a value the backend has never actually had. Per this protocol's own instruction, the right move in a future phase is to *extend* the existing enum (add `PROCESSING`, `CANCELLED`, `PARTIALLY_REFUNDED`) rather than replace it, and reconcile the frontend type once the backend catches up.
5. **No `PaymentProvider` abstraction exists.** All Razorpay-specific logic (signature verification, the fields it reads/writes) lives directly inside `app/services/payments.py`, not behind an interface — exactly the "scattered Razorpay-specific code" this protocol says to avoid. Building the abstraction is a structural, not additive, change to this file.

## Structural correction to the master command's stated tree

The master command's directory tree shows:
```
business-web/
├── Restaurant Owner Portal
└── Admin Portal
```
This does not match the actual repository. There are **four** independent frontend apps at the repo root — `customer-mobile`, `rider-mobile`, `business-web` (Restaurant Owner Portal only), and **`admin-web`** (Admin Portal, its own separate app, own `package.json`, own dev server). This was a deliberate architectural decision from earlier work in this project (each portal is a fully independent app sharing only the backend), not an oversight to fix — noted here so future phase work in this protocol targets the correct app when touching admin-facing payment UI.

## Recommendation for Phase 2 onward

Nothing in this phase requires a code change — the system today handles COD correctly and end-to-end, and online payments are honestly disabled rather than broken. The concrete, ordered list of what a future phase would need to actually build a production Razorpay integration, based on everything above:

1. Reconcile the `PaymentStatus` enum (add `PROCESSING`, `CANCELLED`, `PARTIALLY_REFUNDED`; align `admin-web`'s type).
2. Build the `PaymentProvider` abstraction and a real `RazorpayProvider` (actual Orders API call, actual signature verification already exists and can move in as-is).
3. Retire or fold the generic `POST /payments` path into the new abstraction — never let a client dictate its own provider.
4. Add a `PaymentAttempt` model if attempt-level history is wanted (currently a single mutable row).
5. Add a real `Refund` model and an admin-gated refund flow (state check, approval, actual Razorpay refund call) before removing or replacing the current ungated customer-facing one.
6. Wire the webhook endpoint's already-verified payload into an actual payment-status update.
