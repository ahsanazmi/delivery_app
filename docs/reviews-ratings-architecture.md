# Reviews & Ratings System — Architecture

This document designs the Reviews & Ratings System around what Phase 1's audit (`docs/reviews-ratings-audit.md`) found already exists, rather than around a greenfield plan. Every decision below either **extends** a real, working piece of the current system, or explicitly closes a gap the audit confirmed is missing. Phases 3 onward implement against this document; it is the thing to update if a later phase's own investigation changes a decision made here.

---

## 1. Review lifecycle

```text
Order placed
      ↓
Order DELIVERED  (rider/admin-only transition — audit §2: customer cannot reach this state directly)
      ↓
Review eligibility window opens
      ↓
Customer submits review  (restaurant rating + delivery/rider rating + optional comment + optional item ratings)
      ↓
Backend re-verifies: ownership, DELIVERED status, not already reviewed
      ↓
Review stored (status = PUBLISHED)
      ↓
Aggregates recomputed synchronously, same transaction  (Restaurant.average_rating / total_ratings,
                                                          rider average_rating / total_ratings,
                                                          menu item average_rating / total_ratings if item-rated)
      ↓
Visible to: restaurant owner (their restaurant's reviews), rider (their own rating summary, aggregated — see §6),
            public restaurant/menu listing (aggregate only), admin (everything)
      ↓
Editable by the customer within the edit window (§8), or removable by the customer (§9) — both re-run aggregation
      ↓
Optionally reported by any authenticated user → admin moderation (§5) → status change → aggregation excludes it
```

This is a straight extension of the flow `services/reviews.py: create_order_review` already implements (audit §Backend/Service layer) — eligibility, ownership, and duplicate-prevention are not being rebuilt, only the pipeline around them.

---

## 2. One review row per order — no new polymorphic model

**Decision:** keep the existing `Review` table and its order-review columns (`order_id`, `restaurant_rating`, `delivery_rating`) as the single source of truth for order reviews. Do **not** build a second, more "general" polymorphic review system.

The audit found two surfaces already sharing one table: a legacy generic per-target shape (`target_type`/`target_id`, used by nothing today) and the order-review shape (used by everything). Going forward:

- All new fields (`status`, item ratings, images) attach to the **order-review shape**.
- The generic `target_type`/`target_id` columns and the `/reviews/*` legacy endpoints are **frozen** — left as-is for backward compatibility, never extended. New phases do not add features to them.
- `rider_id` is already a column on `Review`, populated from `order.rider_id` at creation time — the "rider review" this command's Phase 11 asks for is **not a new entity**, it is the existing `delivery_rating` column, already scoped to the rider who delivered that specific order. Phase 11 only needs to confirm/harden the validation that `rider_id` matches the order's actually-assigned rider (it already does, via `order.rider_id` at write time) — there is no new rider-review table to design.

This satisfies Rule 6 (don't mix rating dimensions) by keeping `restaurant_rating` and `delivery_rating` as distinct columns that are aggregated independently (§4), while satisfying Phase 4's "avoid unnecessary polymorphic complexity" by keeping them on one row instead of three separate tables joined by a common key.

---

## 3. Item/menu-item reviews — 🔒 out of scope for the MVP (Phase 5 decision)

**Decision (Phase 5, confirmed with the product owner): item-level ratings are not built for the MVP.** This system ships with restaurant ratings and rider/delivery ratings only. This is a deliberate scope decision, not a gap — the design below is kept as the reference design to build from *if* this is revisited later, per the master command's own Rule 8-adjacent instruction ("if not required for the MVP, document as future scope rather than introducing unnecessary storage complexity"). Nothing in Phases 6 onward depends on this table existing: migrations, aggregation, moderation, and every UI phase are scoped to restaurant + rider ratings only. Any later phase text that assumes item ratings (Phase 12 "item rating submission," Phase 32 "menu item rating integration") is skipped/marked not-applicable rather than built against a table that doesn't exist.

### Reference design (not built — kept for a future revisit)

**Decision:** if item-level ratings are built (Phase 5/12), add a new table:

```text
review_items
  id
  review_id    FK -> reviews.id, CASCADE
  product_id   FK -> products.id, CASCADE      ← real FK, unlike the legacy target_id string
  rating       1-5, CheckConstraint
  comment      Text, nullable
  UniqueConstraint(review_id, product_id)        -- one rating per item per review
```

Rationale: a single order can contain multiple menu items, so item ratings are inherently one-to-many from a review — a single extra column on `Review` cannot represent that. A child table with a real foreign key to `Product` also fixes the audit's §1 finding that the legacy `target_id` is a loose, unenforced string with no referential integrity.

**Validation at write time** (Phase 12): the service layer must verify every `product_id` submitted was actually a line item on the reviewed order (join through the order's line items, not trusted from the client) — this is the same category of check as "customer owns order," just scoped one level deeper.

If item-level ratings turn out not to be required for the MVP, this table is simply never created — nothing above it depends on its existence (restaurant/rider aggregation, §4, does not read from it).

**Phase 4 confirmation:** this is the formal "review target model" determination that phase asked for. `RESTAURANT` and `RIDER` targets are represented by the real FK columns already on `Review` (`restaurant_id`, `rider_id`) — not by a shared generic "target" table — because both are always exactly one row's worth of relationship to a single order (one restaurant, one rider, per order), which a dedicated column models more simply and with real referential integrity than a polymorphic `target_type`/`target_id` pair ever could. `FOOD`/item-level targets are the one genuinely one-to-many case, which is why they get the separate `review_items` child table above rather than being forced onto `Review` directly or routed through the legacy generic target columns. The legacy `target_type`/`target_id` enum/columns remain exactly as the audit found them — present, frozen, never extended — so no third representation is introduced alongside these two.

---

## 4. Aggregation — synchronous recompute, not a background job

**Decision:** ratings aggregates are recomputed **synchronously, in the same DB transaction** as whatever write changed the underlying review set (create, edit, delete, or a moderation status change) — the same philosophy already chosen for notifications (`docs/notification-architecture.md` §10: no new background job infrastructure introduced for this system either).

- `Restaurant.average_rating` / new `Restaurant.total_ratings` — recomputed from `AVG(restaurant_rating)` / `COUNT(*)` over that restaurant's `PUBLISHED` reviews, every time a review touching that restaurant changes. This closes the audit's single highest-priority gap: the column exists and is already read (including the restaurant discovery sort), but nothing writes it today.
- A new `average_rating` / `total_ratings` pair on the rider model (`delivery_partner.py`, audit confirmed neither exists) — recomputed from `AVG(delivery_rating)` / `COUNT(*)` over that rider's `PUBLISHED` reviews.
- A new `average_rating` / `total_ratings` pair on `Product`, only if §3's `review_items` table is built — recomputed from that item's own `PUBLISHED`-review rows.

**Always recompute from a live aggregate query scoped to `status = PUBLISHED`, never an incremental running sum.** An incremental counter (`+= new_rating`, `-= old_rating` on edit/delete) drifts the moment any edge case is missed (a moderation action, a concurrent edit) and there is no way to detect the drift later. A full `AVG()`/`COUNT()` over the current `PUBLISHED` rows is always correct by construction and, at this platform's scale, cheap — this is the same "deterministic over clever" preference already visible in how `average_rating_for_target` was originally written (audit §Backend: it already recomputes from scratch, it just never got wired to persist the result).

This is what makes moderation (§5) and deletion (§9) "just work" for aggregates: removing a review from the `PUBLISHED` set and re-running the same recompute function handles both cases with one code path, not two.

---

## 5. Moderation

**Decision:** add a `status` column to `Review` — `PUBLISHED` (default) / `HIDDEN` / `FLAGGED` / `REMOVED` — modeled directly on the `DocumentVerificationStatus` precedent the audit found in `rider_document.py` (§Admin moderation precedent), not a new pattern.

- **Visibility rule:** only `PUBLISHED` reviews are ever returned by public-facing read endpoints (restaurant review list, rider rating view, menu item ratings) or counted in aggregation (§4). `HIDDEN`/`FLAGGED`/`REMOVED` reviews remain visible to: the admin (moderation queue), and the original reviewing customer (their own review history always shows their own review regardless of status, per Phase 15's "do not expose hidden/removed moderation information unnecessarily" — the customer sees their review is no longer public, not the internal status machinery).
- **Who can change status:** admin only, via a new `admin/reviews.py` endpoint. Every status change writes an `AdminAuditLog` row in the same transaction (audit §Admin moderation precedent — the existing, required pattern for any admin mutation), capturing `previous_state`/`new_state` and the admin's stated reason.
- **Moderation is policy-driven, not rating-driven** (Rule 8): there is no automatic action tied to a low rating. `FLAGGED` is reached only via a report (§6) or direct admin action, never automatically from the rating value itself.
- **Restoration:** an admin can move a review back from `HIDDEN`/`FLAGGED` to `PUBLISHED` (also audited); aggregation re-includes it on the next recompute.

---

## 6. Authorization model

No new authorization primitives — every check below reuses the existing role-dependency pattern (`require_customer`, `require_rider`, `require_restaurant_owner`, `require_admin` — whatever this codebase's existing dependency names are per role) already used by every other endpoint family.

| Actor | Can do |
|---|---|
| Customer | Submit/edit/delete **their own** review (`Review.user_id == current_user.id`) for **their own** delivered order. Read their own review history. |
| Restaurant owner | Read reviews where `Review.restaurant_id` belongs to a restaurant they own (same ownership-filter pattern already used for `business-web` order/product endpoints). Respond to a review (§7). Cannot edit the rating, cannot delete, cannot change status. |
| Rider | Read **only their own** aggregated rating summary and their own recent feedback (`Review.rider_id == current_user.id`, derived from `DeliveryPartner.user_id`, never a rider-supplied ID). Cannot see the reviewing customer's identity beyond whatever the public review view already allows (§8 privacy). |
| Admin | Read/filter/moderate all reviews; every moderation action audited (§5). Cannot fabricate a review or alter its rating/comment — admin authority is over *visibility*, not content. |

The eligibility chain for *submission* specifically (customer → owns order → order DELIVERED → not already reviewed) is unchanged from the audit's §Backend/Service layer description — this table only adds the *read-side* and *moderation-side* authorization that did not exist before.

---

## 7. Restaurant owner responses

**Decision:** supported, as a nullable `owner_response` / `owner_response_at` pair on `Review` (Phase 20), not a separate table — a response is 1:1 with the review it replies to, and a child table would be strictly more complex for no benefit.

Rules (all backend-enforced, matching Phase 20's own spec exactly):
- Only the owner of the restaurant the review targets may set `owner_response`.
- Setting a response never touches `rating`, `restaurant_rating`, `delivery_rating`, or `comment` — enforced by giving the response its own endpoint (`PATCH /restaurant/reviews/{id}/respond`) that only accepts a response body, not a shared "edit review" endpoint.
- The owner cannot delete the review or change its `status` — those stay exclusively on the customer-delete (§9) and admin-moderation (§5) paths respectively.

---

## 8. Review edit policy

**Decision:** a customer may edit their own review (`update_order_review`, which already exists) only while **both** of the following hold:

1. Within a fixed window from `created_at` — **48 hours**, configurable via a module-level constant (same style as the notification system's `_NOTIFICATION_RETENTION_DAYS_READ`/`_UNREAD` constants) so it can be tuned without a migration.
2. `status == PUBLISHED` — once any moderation action has touched the review, editing is locked; the customer's recourse at that point is to contact support, not to edit around a moderation decision.

Both conditions are enforced **only in the backend service function**, never trusted from the client (Rule 3) — `update_order_review` gains the two checks, raising 409 on violation exactly like the existing DELIVERED/duplicate checks it already has.

Every successful edit re-runs aggregation (§4) for every target the review touches (restaurant, rider, and any `review_items` rows that changed).

---

## 9. Review deletion policy

**Decision:** all deletion is a `status` transition, never a hard `DELETE FROM reviews` — this keeps one code path for aggregation (§4: always recompute from `status = PUBLISHED`) instead of two, and preserves history for any later dispute.

- **Customer self-delete:** allowed only within the same window as §8 (48 hours, `status == PUBLISHED`) — sets `status = REMOVED`. No `AdminAuditLog` entry (it's not a moderation action; it's the owner exercising their own right over their own content).
- **Admin removal:** sets `status = REMOVED` with a required reason, audited exactly like any other moderation status change (§5) — indistinguishable in storage from a self-delete except for the presence of an audit log row and the admin's reason.
- **Restaurant owner can never remove a review** (Rule 9/Phase 29, explicit): no endpoint accessible to `RESTAURANT_OWNER` ever writes `Review.status`.
- A `REMOVED` review is excluded from aggregation and from every public/owner/rider read surface, same as `HIDDEN` — the only practical difference between the two statuses is intent (`HIDDEN` = temporarily suppressed pending review; `REMOVED` = final).

---

## 10. Reporting

**Decision:** build a small, review-scoped `ReviewReport` model — not a generic cross-entity `Report`/`Complaint` system, since the audit confirmed none exists today and this codebase's convention (per-feature tables, no premature generic abstractions) argues against inventing one now for a single use case.

```text
review_reports
  id
  review_id    FK -> reviews.id, CASCADE
  reporter_id  FK -> users.id, CASCADE
  reason       enum: SPAM / ABUSIVE / HARASSMENT / FAKE_REVIEW / PERSONAL_INFORMATION / OTHER
  note         Text, nullable
  created_at
  resolved_at  nullable
  resolved_by  FK -> users.id, nullable   -- the admin who acted on it
```

- Any authenticated user may report a review once (`UniqueConstraint(review_id, reporter_id)` — same one-per-pair pattern as `uq_reviews_order_id`).
- A report does **not** automatically change `Review.status` — it surfaces the review in the admin moderation queue (filterable by "has open reports"); the admin still makes the actual `FLAGGED`/`HIDDEN`/`REMOVED` decision (§5), keeping moderation policy-driven rather than crowd-triggered (Rule 8 applies to reports too: a pile of reports is a signal to review, not an automatic takedown).

---

## 11. Rating validation

Reused, not reinvented — the audit confirmed `Field(ge=1, le=5)` integer validation and a 1000-character comment cap already exist in `schemas/review.py`. Phase 13 adds, on top of that:

- Reject a comment that is only whitespace (`comment.strip()` empty → treat as `None`, don't store empty strings).
- No additional language/script filtering — Unicode text passes through unchanged (Rule 8's "do not reject legitimate multilingual text" applies directly).
- No profanity/abuse auto-filtering at submission time — abuse is handled after the fact via reporting (§10) and moderation (§5), not a write-time blocklist, consistent with "do not implement overly aggressive automated censorship" (Phase 14's own instruction).

---

## 12. Review images

**Decision (tentative, confirmed at Phase 34):** if built, follow the audit's confirmed codebase convention exactly — a `String(2048)` URL column(s), with the client responsible for uploading to external storage first (audit §Image/file upload infrastructure: this is the *only* file-handling pattern anywhere in this backend; there is no precedent for a new upload endpoint and this system should not introduce the first one). A small `review_images` child table (`review_id`, `url`, `display_order`) if more than one image per review is wanted, mirroring §3's `review_items` shape.

If the product requirement doesn't actually need images, Phase 34 documents that decision and nothing is built — no code is scaffolded speculatively ahead of that decision.

---

## 13. Notification integration

Review reminders and new-review alerts follow the existing one-function-per-event convention exactly (audit §Notification integration point) — no generic "review event" dispatcher is introduced.

```text
notify_customer_review_reminder(db, order)      -- new, Phase 17
notify_restaurant_new_review(db, review)        -- new, Phase 35
notify_rider_rating_updated(db, review)         -- new, Phase 35
```

Each gated by the existing per-user preference check and wrapped in the existing `_notification_failure_boundary`, so a notification failure can never block a review write (Rule 7). The reminder's *timing* policy (Phase 18 — initial reminder, optional one follow-up, hard-stop once reviewed) is a scheduling decision deferred to that phase; architecturally it is just another caller of the same `notify_*` convention, triggered from wherever the DELIVERED transition already happens (`rider_deliveries.py`), not a new background scheduler.

---

## 14. Privacy

- Review read endpoints (restaurant-owner view, rider view, public listing) never return the reviewing customer's phone, address, or payment information — only whatever minimal identity the product wants shown (e.g. a display name or "Customer", decided at Phase 16/19 UI time), matching Rule 9 exactly.
- `HIDDEN`/`REMOVED` reviews are never returned to the restaurant owner, rider, or public — only to the admin and the original author (§5).
- `ReviewReport.reporter_id` is visible only to admins — a reported-on customer whose review is being moderated is never told *who* reported them, only (optionally) the stated reason category.
- Review images (§12), if built, are never served from a URL that bypasses the same per-review authorization already governing the review's text — no separate, unauthenticated image-serving path.

---

## 15. Summary for implementers of later phases

- **Phase 3 (domain model):** add `status` to the existing `Review` table — do not create a new review table.
- **Phase 4 (target model):** already resolved by §2 — no polymorphic redesign, the order-review shape is canonical.
- **Phase 5 (item reviews):** build `review_items` per §3, only if required.
- **Phase 6 (migration):** one migration adding `status` to `reviews`, `total_ratings` to `restaurants` and the rider model, chained off head `20261009_55`; a second migration later for `review_items` + `review_reports` if/when those phases land.
- **Phases 7–13:** harden the existing eligibility/validation code already described in the audit; no new architecture, just the enforcement of §8/§9's windows and §11's whitespace rule.
- **Phases 19–22:** build the read/response/moderation endpoints per §6/§7/§5 — all net-new routers, no new authorization primitives.
- **Phases 25–27:** implement §4's synchronous recompute — this is the single most load-bearing piece of new logic in the whole system, since the restaurant discovery sort already silently depends on it being correct.
