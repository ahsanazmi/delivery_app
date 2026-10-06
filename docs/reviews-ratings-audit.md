# Reviews & Ratings System — Phase 1 Audit

**Status key:** ✅ already implemented and working · ⚠️ exists but incomplete against this master command's own checklist · ❌ does not exist at all.

**Headline finding:** this is not a greenfield build. A real, working (but partial) review system already exists end-to-end — model, migrations, a backend service layer, a customer-facing API, and a customer-mobile UI component wired directly into the order-detail screen. The gaps are narrower than the full 48-phase command implies, but real: `Restaurant.average_rating` is a column that is read everywhere (including the restaurant sort order) but **written nowhere** — it is permanently `0.00` in practice. There is no rider rating, no menu-item rating field, no admin moderation of reviews, no review images, and no review UI at all outside customer-mobile.

---

## Backend

### Models (✅ exists, ⚠️ incomplete against this command's own target shape)

**`app/models/review.py`** — `Review` (table `reviews`) already exists, with a `ReviewTarget` enum (`RESTAURANT`, `FOOD`, `RIDER`, lines 11–14) and two overlapping sets of fields on the same row:

- A generic per-target shape (lines 32–42): `user_id` (FK `users`, CASCADE), `restaurant_id` (FK `restaurants`, nullable), `rider_id` (FK `users`, SET NULL), `target_type`, `target_id` (a loose `String(64)`, **not a FK** — no referential integrity to `Product`/`Restaurant`/rider), `rating` (1–5, `CheckConstraint`), `comment` (`Text`, nullable).
- An order-review shape added later ("Phase 16" per its own code comment, lines 44–50): `order_id` (FK `orders`, CASCADE, **`UniqueConstraint uq_reviews_order_id`** — hard one-review-per-order enforcement at the DB layer), `restaurant_rating` (1–5), `delivery_rating` (1–5), each independently `CheckConstraint`-validated.

The comment at lines 44–47 explains the duplication deliberately: `rating`/`target_type`/`target_id` are kept populated (mirrored from `restaurant_rating`) on every order-review row too, so the older generic per-target endpoints keep working against the same table.

Registered in `app/models/__init__.py` (lines 23, 71–72).

**Missing against this command's target shape:** no `status` field at all (no `PUBLISHED`/`HIDDEN`/`FLAGGED`/`REMOVED` — Phase 3/14 gap), no separate item-level review rows (Phase 5 — `target_id` is the only thing that could represent a menu item today, and nothing links it back to `Product.id`), no image column (Phase 34 gap).

**`app/models/restaurant.py` line 47** — `average_rating: Mapped[Decimal] = mapped_column(Numeric(3,2), default=Decimal("0.00"))`, range-checked 0–5. **Grepped every write site in `backend/app/services/` and `backend/app/api/`: nothing ever assigns to this column except its default.** It is read in three places — `services/restaurants.py:146` (`ORDER BY Restaurant.average_rating.desc()`, i.e. restaurant discovery sort order is silently a no-op today since every row is `0.00`), `services/admin_restaurants.py:74`, and `schemas/restaurant.py:88,110` — but the actual per-restaurant average computed by `average_rating_for_target()` (below) is never persisted back onto it. This is the single most important gap this system needs to close.

**`app/models/product.py`** (the menu-item model, lines 28–47) — **no rating-related field of any kind.** `ReviewTarget.FOOD` exists as an enum value, but `Product` itself has zero awareness of reviews.

**`app/models/delivery_partner.py`** (the rider model, 66 lines) — **no rating field of any kind**: only `approval_status`, `vehicle_type`, `vehicle_number`, `vehicle_model`, `is_online`. A rider `average_rating`/`total_ratings` pair would be entirely new.

**No `total_ratings`/review-count column exists anywhere** (restaurant, rider, or product) — every "N ratings" display this command's later phases ask for would need `COUNT(*)` on `reviews` at read time, or a new counter column, today.

### Migrations (✅ precedent to follow)

Reviews already has its own migration history: `20260907_01_add_payments_reviews_coupons.py` (original `reviews` table) and `20260910_05_add_order_review_fields.py` (added `order_id`/`restaurant_rating`/`delivery_rating` + the unique constraint). Naming convention confirmed across the whole directory: `YYYYMMDD_NN_short_snake_case_description.py`, `revision`/`down_revision` as the `YYYYMMDD_NN` prefix string (not the full filename). **Current head: `20261009_55`** (`add_notification_retention_index.py`) — any new migration chains off `down_revision = "20261009_55"`.

### Service layer (✅ exists, split across two unreconciled surfaces)

**`app/services/reviews.py`** (119 lines) — two parallel sets of functions:

1. Generic per-target: `create_review(db, *, user_id, target_type, target_id, rating, comment, restaurant_id=None, rider_id=None)`, `list_reviews_for_target(db, *, target_type, target_id)`, `average_rating_for_target(db, *, target_type, target_id)` (computes the live average by summing `list_reviews_for_target` results — correct, but **on-the-fly only, never cached/persisted**).
2. Order-review (the one actually used): `create_order_review(db, user_id, order_id, *, restaurant_rating, delivery_rating, comment)`, `get_order_review(db, user_id, order_id)`, `update_order_review(db, user_id, review_id, *, restaurant_rating, delivery_rating, comment)`.

**The eligibility check to reuse everywhere (lines 54–58 of `create_order_review`) is exactly this command's Rule 4, already correctly implemented:**

```python
order = get_user_order(db, user_id, order_id)          # app/services/orders.py:420 — ownership check
if not order:
    raise HTTPException(404, "Order not found")
if order.status != OrderStatus.DELIVERED:
    raise HTTPException(409, "Only delivered orders can be reviewed")
```

followed immediately by the one-review-per-order guard (`Review.order_id == order_id` lookup, backed by the DB unique constraint — enforced at both layers, per this command's Rule 5).

`get_user_order(db, user_id, order_id)` (`app/services/orders.py:420`) is a plain `WHERE user_id = ... AND id = ...` filter — already the established "order belongs to this customer" pattern, reused by `cancel_order` too.

**Gap:** `update_order_review` has **no time-window or status check at all** — a customer can edit their review indefinitely, any time, with no "edit period" policy (Phase 28 is entirely open). There is also no `delete_order_review` function — reviews cannot be deleted by anyone today, customer or admin (Phase 29 gap).

**Order→DELIVERED transition** (relevant because review eligibility trusts it): `app/services/rider_deliveries.py` (~line 653–705) is the only path that sets `OrderStatus.DELIVERED` from the rider side, and it's idempotent (line ~681: re-calling on an already-delivered order is a no-op success, not an error). `app/services/orders.py` has a comment (~lines 115–117) noting there is **no customer-reachable path** to the DELIVERED status — only rider/admin actions reach it — which is good: the customer cannot fake delivery to unlock a review.

### Schemas (✅ exists)

`app/schemas/review.py` — `ReviewCreate`/`ReviewRead` (generic), `OrderReviewCreate`/`OrderReviewUpdate`/`OrderReviewRead` (order-review). All ratings `Field(ge=1, le=5)` — integer 1–5 scale already standard, matching Phase 10/13's target range exactly. `comment: str | None = Field(default=None, max_length=1000)` — a length cap already exists; no explicit Unicode/whitespace/abuse handling beyond that cap (Phase 13 gap).

### APIs (✅ exists, registered twice — needs reconciling, not tripling)

`app/api/v1/router.py`:

- Line 15: `include_router(reviews.router, prefix="/reviews", ...)` → `app/api/v1/endpoints/reviews.py` — the generic per-target surface: `POST /reviews`, `GET /reviews/restaurant/{id}`, `GET /reviews/food/{id}`, `GET /reviews/rider/{id}`, `GET /reviews/average/{type}/{id}`. Its own code comment (lines 13–19) explicitly flags this as **kept only for API-contract consistency — no frontend app calls it today.**
- Line 49: `include_router(customer.reviews.router, prefix="/customer", ...)` → `app/api/v1/customer/reviews.py` — the surface actually in use: `POST/GET /customer/orders/{order_id}/review`, `PATCH /customer/reviews/{review_id}`. Correctly scoped to `require_customer` + `current_user.id` on every call.

**No `app/api/v1/restaurant/reviews.py`, `.../rider/reviews.py`, or `.../admin/reviews.py` exist.** A restaurant owner viewing/responding to their restaurant's reviews, a rider viewing their own rating summary, and any admin moderation are all net-new endpoint surfaces.

Directory convention confirmed: `app/api/v1/{customer,restaurant,rider,admin}/` (one router-per-concern file each) plus a flat `app/api/v1/endpoints/` for cross-role/legacy pieces. New work should extend `customer/reviews.py` (already exists) and add new `restaurant/reviews.py`, `rider/reviews.py`, `admin/reviews.py` files following that same pattern — not add a third top-level surface.

### Admin moderation precedent (❌ nothing exists for reviews specifically, ✅ a clear pattern exists elsewhere to copy)

No `HIDDEN`/`FLAGGED`/`REMOVED`-style status exists anywhere in the codebase. The closest real precedent for "moderate user/content-adjacent state with a reason" is `app/models/rider_document.py`'s `DocumentVerificationStatus` (`PENDING`/`APPROVED`/`REJECTED`) + `rejection_reason`, moderated via `app/services/rider_documents.py: review_rider_document(...)` and called from `app/api/v1/admin/riders.py`. This is the template a future review-moderation feature should follow.

Generic audit trail: `app/models/admin_audit_log.py` — `AdminAuditLog` (`admin_id`, `action` free-string, `target_type`/`target_id` free-string — same loose shape as `Review.target_type`/`target_id`, `reason`, `previous_state`/`new_state`, `created_at`), explicitly written in the **same DB transaction** as the mutation it records. This is the precedent any admin "hide/remove a review" action should follow.

### Complaint/report system (❌ confirmed absent)

No `Report` or `Complaint` model exists anywhere (`grep -rln "class Report\|class Complaint"` → zero matches). `app/services/admin_reports.py`/`app/schemas/admin_reports.py` exist but are **business-intelligence reports** (revenue, orders-by-status, top customers) — an unrelated use of the word "report," not a content-flagging system. Phase 23's reporting feature, if built, starts from nothing.

### Image/file upload infrastructure (❌ no backend upload endpoint exists — ✅ a clear URL-only convention to follow)

No `UploadFile`, no multipart handling, no S3/boto3 usage anywhere in `backend/app`. The established, explicit convention (stated in `app/models/rider_document.py`'s own comment, lines ~26–34): the backend never receives raw file bytes — the client uploads to external storage itself and sends back only a URL, stored as a plain `String(2048)` column (used identically for `Restaurant.logo_url`, `Product.image_url`, `RiderDocument.document_url`). Review images, if built (Phase 34), should follow this exact convention — add a URL column (or a small child table for multiple images), not a new upload endpoint.

### Pagination convention (✅ exists, ⚠️ not fully consistent across the codebase already)

Convention is page/limit (or raw offset/limit) on the wire, converted to `.offset().limit()` at the service layer, returning a **bare list** — no envelope, no cursor anywhere in the codebase. `customer/orders.py` exposes `page`/`limit` (converted to offset); `customer/restaurants.py` exposes `offset`/`limit` directly — both styles exist today, so either is acceptable for new review-list endpoints. Notifications' list endpoint is the one deliberate exception (capped at 100 rows, no pagination at all) — not a pattern to copy here given reviews can grow large per popular restaurant.

### Notification integration point (✅ exists, no generic helper — one function per event is the convention)

There is no generic `create_notification(...)` helper. `app/services/notifications.py` instead has one dedicated `notify_*` function per business event (e.g. `notify_order_placed`), each following: a `_user_wants(...)` preference gate, a `_notification_failure_boundary(...)` context manager isolating failures from the caller's transaction, a `db.add(Notification(...))`, and a `send_push_to_user(...)` call. A review-reminder notification (Phase 17) should add a new `notify_customer_review_reminder(db, order)` following this exact template, plus a new `NotificationType` enum value — not try to call a generic helper, since none exists.

---

## Customer Mobile (✅ a real, working review UI already exists)

- `components/order-review.tsx` (199 lines) — the existing review UI component, `OrderReviewSection`.
- `services/api/reviewsApi.ts` — typed client: `getOrderReview`, `createOrderReview`, `updateOrderReview`, hitting exactly the `customer/reviews.py` endpoints above.
- **`app/orders/[id].tsx`** imports `OrderReviewSection` and renders `<OrderReviewSection accessToken={accessToken} orderId={order.id} />` directly on the order-detail screen (line ~361) — this is already the live "rate this order" entry point Phase 16's design describes. Any new review UI work extends this screen, it doesn't invent a new one.
- Rating is already rendered read-side too: `app/home.tsx:305`, `features/restaurants/restaurant-list.tsx:44`, `app/restaurants/[id].tsx:203–204` all render `★ {Number(restaurant.rating).toFixed(1)}` against the `average_rating` field — currently always showing `0.0` in practice, since nothing ever writes that column (see Backend above). Fixing the write path fixes these displays with zero frontend changes needed.
- **No `features/reviews/` folder** — the existing code lives flat in `components/`/`services/api/`, not under its own feature directory. Worth promoting if this system grows, but not required.
- No review reminder/deep-link handling exists yet in `features/notifications/notification-provider.tsx`'s `handleDeepLink` switch — Phase 17/27-equivalent work would add a case here once the new `NotificationType` exists.

## Rider Mobile (❌ nothing exists)

No file, route, or string match for review/rating/star content anywhere in `rider-mobile` (confirmed by grep — only incidental unrelated word collisions). A rider "my ratings" screen (Phase 21) is entirely new: no feature folder, no API client function, no screen.

## Business Web — restaurant owner portal (❌ nothing exists)

No review-related file or UI anywhere in `business-web/src`. A restaurant owner's "my reviews" page (Phase 19/20) is entirely new — would likely live at `src/pages/restaurant/Reviews.tsx` alongside the existing `Dashboard.tsx`/`Products.tsx`/`OrderDetails.tsx`.

## Admin Web (❌ nothing exists)

No review or moderation UI anywhere in `admin-web/src`. Admin moderation of reviews (Phase 22) is entirely new on both backend (confirmed above — no status/flag field, no moderation endpoint) and frontend.

---

## Summary: what's reusable vs. what's net-new

**Reuse as-is:**
- `Review`/`ReviewTarget` model and its two existing migrations.
- `get_user_order` ownership pattern + the DELIVERED-only eligibility check in `create_order_review`.
- The DB-level `UniqueConstraint` + application-level duplicate-review guard (Rule 5 already satisfied for order reviews).
- `customer/reviews.py` endpoints and `services/reviews.py`'s order-review functions.
- customer-mobile's `OrderReviewSection` + `reviewsApi.ts`, already wired into `app/orders/[id].tsx`.
- The admin audit-log pattern (`AdminAuditLog`) and the `rider_document.py` PENDING/APPROVED/REJECTED-style moderation template, for when admin review moderation is built.
- The offset/limit pagination convention and the one-function-per-event notification convention.
- The URL-only, no-backend-upload file convention, for review images.

**Must build net-new (confirmed absent, not just incomplete):**
- A write path that actually recomputes and persists `Restaurant.average_rating` (and a `total_ratings` counter) whenever a review is created/edited/deleted — the single highest-priority gap, since restaurant sort order already silently depends on it.
- `average_rating`/`total_ratings` on the rider model (`delivery_partner.py`) — does not exist at all.
- Any rating field or review linkage on `Product` (menu items) — does not exist at all; `target_id` on `Review` has no FK to enforce "customer actually purchased this item."
- A `status` field on `Review` (published/hidden/flagged/removed) and any admin moderation endpoint — neither exists.
- A `Report`/`Complaint` model for flagging reviews — does not exist (the only "report" in the codebase is unrelated BI analytics).
- Review images — no column, no upload path.
- Review edit window / deletion policy — `update_order_review` has no time limit today; no delete function exists at all.
- Review-reminder notification function + new `NotificationType` + deep-link case.
- Rider-mobile, business-web, and admin-web review UI — none exists in any of the three.
- A decision on reconciling the two parallel backend review surfaces (`/reviews/*` generic-unused vs. `/customer/orders/{id}/review` actually-used) so later phases build on one surface, not three.
