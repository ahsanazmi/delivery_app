# Live Rider Tracking — Location Privacy & History Policy

**Status:** ✅ already true by construction · 🆕 added in this phase

## The core rule: latest location, not history

Every read path in this codebase — `list_available_deliveries`' distance estimate, the customer tracking snapshot, the restaurant/admin operational views (Phase 27) — reads `User.current_latitude/current_longitude/current_accuracy/current_heading/current_speed/location_updated_at`. This is a single row per rider, overwritten on every accepted GPS report. **No endpoint anywhere returns a list of past positions to anyone** — not to the customer, not to the restaurant, not to admin. Confirmed by grepping every consumer of `RiderLocationPing` (the one history table that exists at all): it is read and written *only* inside `app/services/rider_location.py`, for one purpose — deciding whether the current report is close enough in time/space to the last *stored* one to skip writing a new row (Phase 7's throttle). Nothing else touches it.

## Why a history table exists at all, and what it's minimal for

`RiderLocationPing` is the "limited history when genuinely required" this phase's own rule allows for — the genuine requirement being the throttle decision above, an operational necessity that literally cannot be evaluated from the current-position cache alone (that cache only remembers the *latest* point, not "how long ago was the point before that"). It is minimal by construction, not just by policy:

- **Throttled at write time**, not just conceptually — a new row is only inserted once ≥10s or ≥15m has passed since the last stored one for that rider (Phase 7). A rider on a 12-second foreground interval for an entire 8-hour shift produces on the order of a few thousand rows over the whole shift, not tens of thousands.
- **No FK-less orphaning** — Phase 3 added `assignment_id`/`order_id` (both nullable, since a rider can be online with no assignment yet) specifically so a row can be tied to which delivery it belonged to, `ON DELETE SET NULL` if that order/assignment is ever removed — never a dangling reference nobody can account for.
- **No endpoint reads it back.** This table exists purely as a write-side operational detail of the throttle; it isn't wired to anything a customer, restaurant, or admin can query today.

## Access restriction

- **Customer:** cannot access history at all (no endpoint exists). Cannot access even the *live* position of a rider not currently assigned to their own order (Phase 15/24/30's authorization boundaries).
- **Rider:** cannot query anyone else's location, history or otherwise — `update_rider_location` operates on `current_rider` (from the JWT) with no `rider_id` parameter for a client to redirect (Phase 6).
- **Restaurant/Admin (Phase 27):** the *latest* position only, time-boxed to `LOCATION_VISIBLE_STATUSES` (an order actively being delivered) — never the history table, never for a completed/cancelled order, never for a delivery that isn't theirs.

## 🆕 Retention

No automated purge job exists yet in this codebase (there is no scheduled-task/cron infrastructure here at all today — adding one solely for this would be new infrastructure disproportionate to the actual data volume, given the throttle already keeps this table small). What this phase adds instead:

- **A documented retention window: 30 days.** `RiderLocationPing` rows older than 30 days have no remaining operational purpose (the throttle only ever looks at the single most recent row per rider; nothing else reads this table at all) and should not be kept indefinitely.
- **A ready-to-run purge function**, `purge_rider_location_history(db, older_than_days=30)` (`app/services/rider_location.py`) — a plain, safe bulk delete, callable from a one-off admin script or wired into a scheduler if/when this project adds one. Not run automatically by anything yet; this phase's job is to make the retention policy real and actionable, not to build a scheduler that doesn't otherwise exist here.

## Explicitly out of scope for this phase

- A restaurant/admin history *browser* (a UI to scroll through a rider's past pings) — nothing in this codebase's actual requirements has asked for one, and building it would directly contradict "avoid customer/staff access to raw history" as a default. If a genuine operational need for it emerges later (a dispute investigation, say), it should be its own explicitly-scoped, access-logged feature — not an incidental side effect of this phase.
- Automated scheduling of the purge function — see above.

## 🆕 Observability doesn't reopen this (Phase 39)

The structured tracking-event logs (`docs/live-tracking-architecture.md` §14) never log a coordinate, a name, an email, a phone number, or raw address text — every field is an id, a status, or a short reason string. A log line proving "rider X reported a location for order Y" exists; one containing *where* does not. See `docs/troubleshooting.md` for how to use these events without needing to add anything more sensitive to debug an issue.
