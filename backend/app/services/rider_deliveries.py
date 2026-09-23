import logging
from datetime import UTC, datetime
from decimal import Decimal
from math import atan2, cos, radians, sin, sqrt
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.cod_collection import CodCollection
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.notification import NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User
from app.schemas.rider_delivery import AvailableDeliveryRead, CodCollectionRead, RiderDeliveryDetailRead
from app.services.notifications import notify_admins
from app.services.orders import transition_order_status
from app.services.rider_earnings import record_delivery_fee_earning
from app.services.rider_dashboard import RIDER_ACTIVE_STATUSES
from app.services.rider_service import assert_rider_approved, get_or_create_delivery_partner

logger = logging.getLogger(__name__)

# Admin Portal Phase 20 — "COD settlement due" threshold. A documented,
# adjustable business rule, not derived from anything: once a rider's
# outstanding (collected minus remitted) COD balance reaches this amount,
# admins get an alert on every further collection until the rider settles.
# There is no de-duplication — an admin may see repeated alerts for the same
# rider while they remain over the threshold.
COD_SETTLEMENT_DUE_THRESHOLD = Decimal("1000.00")

_EARTH_RADIUS_KM = 6371.0

# Performance Baseline (Phase 25) — list_available_deliveries had no cap at
# all: every unassigned READY_FOR_PICKUP order platform-wide, regardless of
# how many restaurants or cities. A busy platform could hand one rider's
# device hundreds of rows on every poll. Capped the same defensive way
# admin_dashboard's own recent-lists already are; oldest-ready-first
# ordering (unchanged) means a rider still sees the orders that have been
# waiting longest, not an arbitrary truncation.
AVAILABLE_DELIVERIES_LIMIT = 50

# Phase 24 — the single choke point for every DeliveryAssignment.status
# mutation, mirroring transition_order_status()'s VALID_TRANSITIONS in
# orders.py exactly. The phase's own vocabulary (PENDING/ACCEPTED/PICKED_UP/
# OUT_FOR_DELIVERY/DELIVERED/REJECTED/CANCELLED) maps onto this table as
# follows: PENDING is `None` — there is deliberately no persisted row before
# a rider actually acts (see DeliveryAssignment's own docstring) — and
# ARRIVED_AT_RESTAURANT is an optional Phase-13 sub-step of ACCEPTED that
# doesn't appear in the phase's simplified diagram but fits naturally between
# ACCEPTED and PICKED_UP. Every entry is terminal-or-not exactly once:
# DELIVERED, REJECTED, and CANCELLED all map to an empty set — nothing moves
# a delivery on from any of them, which is what makes
# "REJECTED -> ACCEPTED", "DELIVERED -> PICKED_UP", and "PENDING -> DELIVERED"
# all correctly rejected below.
ASSIGNMENT_VALID_TRANSITIONS: dict[AssignmentStatus | None, set[AssignmentStatus]] = {
    None: {AssignmentStatus.ACCEPTED, AssignmentStatus.REJECTED},
    AssignmentStatus.ACCEPTED: {
        AssignmentStatus.ARRIVED_AT_RESTAURANT,
        AssignmentStatus.PICKED_UP,
        AssignmentStatus.CANCELLED,
    },
    AssignmentStatus.ARRIVED_AT_RESTAURANT: {AssignmentStatus.PICKED_UP, AssignmentStatus.CANCELLED},
    AssignmentStatus.PICKED_UP: {AssignmentStatus.OUT_FOR_DELIVERY, AssignmentStatus.CANCELLED},
    AssignmentStatus.OUT_FOR_DELIVERY: {AssignmentStatus.DELIVERED, AssignmentStatus.CANCELLED},
    AssignmentStatus.DELIVERED: set(),
    AssignmentStatus.REJECTED: set(),
    AssignmentStatus.CANCELLED: set(),
}


def _transition_assignment_status(
    assignment: DeliveryAssignment | None, new_status: AssignmentStatus, *, idempotent: bool = False
) -> None:
    """Validates and applies one assignment status change. Passing
    `assignment=None` validates against the implicit PENDING (no row yet)
    state without touching anything — used by accept_delivery(), which
    still creates its own row afterward rather than through this function.
    `idempotent=True` lets a caller re-send the same status it's already in
    (e.g. a rider double-tapping "Arrived") without that counting as an
    invalid transition — every other move must appear in
    ASSIGNMENT_VALID_TRANSITIONS or this raises a 409."""
    current = assignment.status if assignment else None
    if idempotent and current == new_status:
        return
    allowed = ASSIGNMENT_VALID_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        current_label = current.value if current else "PENDING"
        # Logging & Error Handling (Phase 26) — the single choke point for
        # every DeliveryAssignment.status mutation is also the single place
        # an assignment conflict is logged (double-accept, accept-after-
        # reject, out-of-order pickup/complete, etc.).
        logger.warning(
            "Assignment conflict: rejected transition for assignment %s (%s -> %s)",
            assignment.id if assignment else None, current_label, new_status.value,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot move a delivery assignment from {current_label} to {new_status.value}.",
        )
    if assignment is not None:
        assignment.status = new_status


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    lat1, lon1, lat2, lon2 = (radians(float(v)) for v in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return round(_EARTH_RADIUS_KM * 2 * atan2(sqrt(a), sqrt(1 - a)), 2)


def list_available_deliveries(db: Session, rider: User) -> list[AvailableDeliveryRead]:
    """A rider must be online to see anything here. Checking is_online alone
    is sufficient to also mean "approved": going online at all requires
    APPROVED (Phase 7), and an admin moving a rider off APPROVED forces
    is_online back to False in the same action (Phase 6) — so is_online=True
    can never coexist with a non-approved rider."""
    partner = get_or_create_delivery_partner(db, rider)
    if not partner.is_online:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online to see available deliveries.",
        )

    # Once this rider has rejected an order, it shouldn't keep reappearing in
    # their own list — it's still available to every other rider, though.
    rejected_order_ids = select(DeliveryAssignment.order_id).where(
        DeliveryAssignment.rider_id == rider.id, DeliveryAssignment.status == AssignmentStatus.REJECTED
    )

    orders = list(
        db.scalars(
            select(Order)
            .where(
                Order.status == OrderStatus.READY_FOR_PICKUP,
                Order.rider_id.is_(None),
                Order.id.notin_(rejected_order_ids),
            )
            .order_by(Order.created_at.asc())
            .limit(AVAILABLE_DELIVERIES_LIMIT)
        )
    )

    # Phase 30: batch-fetch every distinct restaurant this page of orders
    # references in a single query, instead of one db.get() per order below
    # — the N+1 this replaces was real (a busy area with orders from many
    # different restaurants ready at once used to mean one extra round trip
    # per order just to get its lat/lng for the distance estimate, since
    # restaurant_name/address are already denormalized onto Order and don't
    # need this lookup at all).
    restaurant_ids: set[UUID] = set()
    for order in orders:
        if order.restaurant_id:
            try:
                restaurant_ids.add(UUID(order.restaurant_id))
            except ValueError:
                pass
    restaurants_by_id: dict[UUID, Restaurant] = (
        {r.id: r for r in db.scalars(select(Restaurant).where(Restaurant.id.in_(restaurant_ids)))}
        if restaurant_ids
        else {}
    )

    results: list[AvailableDeliveryRead] = []
    for order in orders:
        restaurant: Restaurant | None = None
        if order.restaurant_id:
            try:
                restaurant = restaurants_by_id.get(UUID(order.restaurant_id))
            except ValueError:
                restaurant = None

        distance_km: float | None = None
        if (
            restaurant is not None
            and rider.current_latitude is not None
            and rider.current_longitude is not None
        ):
            distance_km = _distance_km(
                rider.current_latitude, rider.current_longitude, restaurant.latitude, restaurant.longitude
            )

        results.append(
            AvailableDeliveryRead(
                assignment_id=order.id,
                order_id=order.id,
                restaurant_name=order.restaurant_name or (restaurant.name if restaurant else "Restaurant"),
                restaurant_address=order.restaurant_address or (restaurant.address if restaurant else ""),
                restaurant_latitude=restaurant.latitude if restaurant else None,
                restaurant_longitude=restaurant.longitude if restaurant else None,
                customer_area=order.city,
                estimated_distance_km=distance_km,
                estimated_earning=order.delivery_fee,
                ready_since=order.updated_at,
            )
        )
    return results


def _assert_rider_online(db: Session, rider: User) -> None:
    partner = get_or_create_delivery_partner(db, rider)
    if not partner.is_online:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Go online to respond to delivery requests.",
        )


def _get_available_order_or_404(db: Session, order_id: UUID) -> Order:
    order = db.scalar(
        select(Order).where(
            Order.id == order_id, Order.status == OrderStatus.READY_FOR_PICKUP, Order.rider_id.is_(None)
        )
    )
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not available")
    return order


def accept_delivery(db: Session, rider: User, order_id: UUID) -> Order:
    """The critical concurrency-safe operation: two riders must never both
    successfully accept the same delivery.

    The guarantee comes from the conditional UPDATE below, not from any
    Python-level check-then-act. Postgres re-evaluates an UPDATE's WHERE
    clause against the row's committed state at the moment it acquires that
    row's write lock — so if two of these run concurrently for the same
    order_id, the database itself serializes them: whichever commits first
    wins (rowcount=1); the second one's WHERE clause then sees rider_id is
    no longer NULL and matches zero rows (rowcount=0), with no explicit
    SELECT ... FOR UPDATE or app-level locking required.

    Phase 28 — idempotent retry: a network drop can lose the response to an
    accept call that actually succeeded server-side. If this exact rider
    already owns this order (whatever stage it's since reached), a retried
    accept returns the current order as success rather than erroring —
    checked before the online/availability checks below, since "you already
    have this" is true regardless of whether the rider is still online.
    """
    already_owned = db.scalar(select(Order).where(Order.id == order_id, Order.rider_id == rider.id))
    if already_owned is not None:
        return already_owned

    _assert_rider_online(db, rider)
    # Pre-check for a clean 404 on a genuinely bad/stale ID — this alone
    # would still be race-prone if relied on for the actual claim, which is
    # exactly why the real guarantee is the UPDATE below, not this check.
    _get_available_order_or_404(db, order_id)

    # Phase 24: a rider who already rejected this exact order (directly, by
    # ID — list_available_deliveries already hides it from their own list,
    # but nothing previously stopped a direct call here) must not be able to
    # turn that REJECTED record into an ACCEPTED one. Checked before the
    # atomic claim below so this is a clean 409, not an unhandled unique-
    # constraint IntegrityError from inserting a second row for the same
    # (order_id, rider_id) pair.
    existing_assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.order_id == order_id, DeliveryAssignment.rider_id == rider.id
        )
    )
    _transition_assignment_status(existing_assignment, AssignmentStatus.ACCEPTED)

    result = db.execute(
        update(Order)
        .where(Order.id == order_id, Order.rider_id.is_(None), Order.status == OrderStatus.READY_FOR_PICKUP)
        .values(rider_id=rider.id)
    )
    if result.rowcount == 0:
        db.rollback()
        # Logging & Error Handling (Phase 26) — the losing side of the
        # accept-delivery race, i.e. a genuine assignment conflict.
        logger.warning("Assignment conflict: order %s already claimed, rider %s lost the race", order_id, rider.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This delivery has already been accepted by another rider.",
        )

    order = db.get(Order, order_id)
    db.refresh(order)
    try:
        transition_order_status(db, order, OrderStatus.RIDER_ASSIGNED, f"Accepted by rider {rider.name}")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    assignment = DeliveryAssignment(
        order_id=order.id, rider_id=rider.id, status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC)
    )
    db.add(assignment)
    db.commit()
    db.refresh(order)
    return order


def reject_delivery(db: Session, rider: User, order_id: UUID, reason: str | None = None) -> DeliveryAssignment:
    """Purely a per-rider record — never touches the order itself, so
    rejecting has no effect on any other rider's ability to accept it."""
    _assert_rider_online(db, rider)
    _get_available_order_or_404(db, order_id)

    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.order_id == order_id, DeliveryAssignment.rider_id == rider.id
        )
    )
    # idempotent=True: a rider re-rejecting an order they'd already rejected
    # (e.g. retrying after a network blip) just refreshes the timestamp/
    # reason rather than being treated as an invalid REJECTED->REJECTED move.
    _transition_assignment_status(assignment, AssignmentStatus.REJECTED, idempotent=True)
    if assignment is None:
        assignment = DeliveryAssignment(order_id=order_id, rider_id=rider.id, status=AssignmentStatus.REJECTED)
        db.add(assignment)
    assignment.rejected_at = datetime.now(UTC)
    assignment.rejection_reason = reason
    db.commit()
    db.refresh(assignment)
    return assignment


def get_rider_delivery_or_404(db: Session, rider: User, order_id: UUID) -> Order:
    """Scoped to rider_id == this rider — an order assigned to someone else,
    still unclaimed, or that never existed is all treated identically as
    "not found", the same "never leak that it exists" pattern used
    throughout every portal in this project."""
    order = db.scalar(select(Order).where(Order.id == order_id, Order.rider_id == rider.id))
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return order


def get_rider_delivery_detail(db: Session, rider: User, order_id: UUID) -> RiderDeliveryDetailRead:
    order = get_rider_delivery_or_404(db, rider, order_id)

    restaurant: Restaurant | None = None
    if order.restaurant_id:
        try:
            restaurant = db.get(Restaurant, UUID(order.restaurant_id))
        except ValueError:
            restaurant = None

    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.order_id == order.id, DeliveryAssignment.rider_id == rider.id
        )
    )

    cod_amount = order.total if (order.payment_method == "cod" and not order.is_paid) else None

    # Phase 15 privacy control: the rider only needs the customer's exact
    # contact details (phone, address line, landmark, coordinates, delivery
    # notes) while the delivery is actually in progress. Once it's DELIVERED
    # or CANCELLED, that operational need is over — those specific fields
    # are hidden from this same endpoint, not by revoking access to the
    # order entirely (the rider can still see what/who they delivered for
    # their own records), just by no longer handing back the means to
    # re-contact or re-locate the customer. Name and general area
    # (city/state/postal code) stay visible either way — neither is a
    # precise way to reach or find someone, and a rider legitimately wants
    # to recall who an order was for.
    delivery_in_progress = order.status in RIDER_ACTIVE_STATUSES

    return RiderDeliveryDetailRead(
        order_id=order.id,
        order_number=order.order_number,
        status=order.status,
        assignment_status=assignment.status if assignment else None,
        restaurant_name=order.restaurant_name or (restaurant.name if restaurant else "Restaurant"),
        restaurant_phone=order.restaurant_phone or (restaurant.phone if restaurant else None),
        restaurant_address=order.restaurant_address or (restaurant.address if restaurant else ""),
        restaurant_latitude=restaurant.latitude if restaurant else None,
        restaurant_longitude=restaurant.longitude if restaurant else None,
        customer_name=order.customer_name,
        customer_phone=order.customer_phone if delivery_in_progress else None,
        delivery_address_line=order.address_line if delivery_in_progress else "Hidden after delivery",
        delivery_city=order.city,
        delivery_state=order.state,
        delivery_postal_code=order.postal_code,
        delivery_landmark=order.landmark if delivery_in_progress else None,
        delivery_latitude=order.latitude if delivery_in_progress else None,
        delivery_longitude=order.longitude if delivery_in_progress else None,
        delivery_instructions=order.delivery_instructions if delivery_in_progress else None,
        items=list(order.items),
        subtotal=order.subtotal,
        delivery_fee=order.delivery_fee,
        total=order.total,
        payment_method=order.payment_method,
        is_paid=order.is_paid,
        cod_amount=cod_amount,
        created_at=order.created_at,
    )


def _get_or_create_assignment(db: Session, order_id: UUID, rider_id: UUID) -> tuple[DeliveryAssignment, bool]:
    """An assignment row should already exist from accept_delivery(), but an
    order can also reach RIDER_ASSIGNED via the admin's own direct
    assign_rider_to_order (Phase 3-era, still reachable) — which never goes
    through this table at all. Falling back to creating one here means
    arrival/pickup tracking works either way, not just for the Phase 10
    accept flow.

    Returns (assignment, existed_before). A freshly backfilled row (Phase 24)
    must NOT be run through ASSIGNMENT_VALID_TRANSITIONS by its caller — it
    may need to jump straight to PICKED_UP or OUT_FOR_DELIVERY, skipping
    ACCEPTED/ARRIVED_AT_RESTAURANT entirely, because the order got there via
    the admin's own path, which was never validated against this table in
    the first place. existed_before tells the caller whether the row already
    reflected a rider-driven history (in which case the choke point applies
    normally) or is only just catching up to reality right now.
    """
    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.order_id == order_id, DeliveryAssignment.rider_id == rider_id
        )
    )
    if assignment is None:
        assignment = DeliveryAssignment(
            order_id=order_id, rider_id=rider_id, status=AssignmentStatus.ACCEPTED, accepted_at=datetime.now(UTC)
        )
        db.add(assignment)
        db.flush()
        return assignment, False
    return assignment, True


def mark_arrived_at_restaurant(db: Session, rider: User, order_id: UUID) -> DeliveryAssignment:
    """Purely informational — Order.status is untouched (it stays
    RIDER_ASSIGNED). Optional by design: nothing requires this to be called
    before pickup_delivery(); it just gives the frontend a place to record
    "I'm here" between accepting and actually picking up the food."""
    order = get_rider_delivery_or_404(db, rider, order_id)
    # Phase 25: a rider suspended after already accepting a delivery must
    # not be able to keep performing it — accept/reject already refuse a
    # non-online rider, but nothing previously stopped a since-suspended
    # rider from continuing one they'd accepted before suspension.
    assert_rider_approved(db, rider)
    if order.status != OrderStatus.RIDER_ASSIGNED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot mark arrival — order is currently {order.status.value}.",
        )
    assignment, existed_before = _get_or_create_assignment(db, order.id, rider.id)
    if existed_before:
        _transition_assignment_status(assignment, AssignmentStatus.ARRIVED_AT_RESTAURANT, idempotent=True)
    else:
        assignment.status = AssignmentStatus.ARRIVED_AT_RESTAURANT
    assignment.arrived_at = datetime.now(UTC)
    db.commit()
    db.refresh(assignment)
    return assignment


def pickup_delivery(db: Session, rider: User, order_id: UUID) -> Order:
    """The real state change: RIDER_ASSIGNED -> PICKED_UP on the order
    itself, via the existing transition_order_status() choke point (no new
    OrderStatus value — PICKED_UP already exists and RIDER_ASSIGNED already
    permits it in VALID_TRANSITIONS, so every other portal's status handling
    needs no changes at all).

    Phase 28 — idempotent retry: if this exact order is already PICKED_UP
    (a lost-response retry of a pickup call that actually succeeded), return
    it as success rather than a 409 — a stale response is not the same
    thing as an invalid transition attempt."""
    order = get_rider_delivery_or_404(db, rider, order_id)
    if order.status == OrderStatus.PICKED_UP:
        return order
    assert_rider_approved(db, rider)
    try:
        transition_order_status(db, order, OrderStatus.PICKED_UP, f"Picked up by rider {rider.name}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    assignment, existed_before = _get_or_create_assignment(db, order.id, rider.id)
    if existed_before:
        _transition_assignment_status(assignment, AssignmentStatus.PICKED_UP, idempotent=True)
    else:
        assignment.status = AssignmentStatus.PICKED_UP
    assignment.picked_up_at = datetime.now(UTC)
    db.commit()
    db.refresh(order)
    return order


def start_delivery(db: Session, rider: User, order_id: UUID) -> Order:
    """PICKED_UP -> OUT_FOR_DELIVERY, via the existing transition_order_status()
    choke point (no new OrderStatus value — OUT_FOR_DELIVERY already exists
    and PICKED_UP already permits it in VALID_TRANSITIONS).

    Phase 28 — idempotent retry: same reasoning as pickup_delivery() above."""
    order = get_rider_delivery_or_404(db, rider, order_id)
    if order.status == OrderStatus.OUT_FOR_DELIVERY:
        return order
    assert_rider_approved(db, rider)
    try:
        transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY, f"Out for delivery — rider {rider.name}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    assignment, existed_before = _get_or_create_assignment(db, order.id, rider.id)
    if existed_before:
        _transition_assignment_status(assignment, AssignmentStatus.OUT_FOR_DELIVERY, idempotent=True)
    else:
        assignment.status = AssignmentStatus.OUT_FOR_DELIVERY
    assignment.out_for_delivery_at = datetime.now(UTC)
    db.commit()
    db.refresh(order)
    return order


def collect_cod_payment(db: Session, rider: User, order_id: UUID) -> CodCollectionRead:
    """Records that this rider collected the Cash on Delivery amount for
    their assigned order. The request carries no body — amount, order and
    rider are all resolved server-side (never from client input), so there
    is no field a rider could tamper with to under- or over-report what they
    collected: the amount recorded is always order.total re-read fresh from
    the database at the moment of collection.

    Only allowed once the order is actually OUT_FOR_DELIVERY — the point at
    which a rider is physically handing the order to the customer — and only
    once, guarded by is_paid so a rider can't "collect" the same cash twice.

    Phase 28 — idempotent retry: if this exact rider already collected this
    exact order's cash (is_paid, and they're the one on record as having
    collected it), a retried call returns that same collection record as
    success rather than a 409 — a lost-response retry isn't a genuine
    double-collection attempt. If is_paid is true for some other reason
    (collected by a different rider, or settled via the legacy admin
    fallback with no rider attribution at all), that's still a real
    conflict, not a safe replay, so it stays a 409.
    """
    order = get_rider_delivery_or_404(db, rider, order_id)
    assert_rider_approved(db, rider)

    if order.payment_method != "cod":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This order isn't Cash on Delivery — there's nothing to collect.",
        )
    if order.status != OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cash can only be collected while out for delivery — order is currently {order.status.value}.",
        )
    if order.is_paid:
        existing_payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
        if existing_payment is not None and existing_payment.collected_by_rider_id == rider.id:
            return CodCollectionRead(
                order_id=order.id,
                payment_id=existing_payment.id,
                amount=existing_payment.amount,
                payment_status=existing_payment.payment_status,
                collected_by_rider_id=rider.id,
                collected_at=existing_payment.collected_at,
            )
        # Logging & Error Handling (Phase 26) — a genuine double-collection
        # attempt (not the safe same-rider retry handled above).
        logger.warning("COD issue: order %s cash already collected, rejected duplicate collection by rider %s", order.id, rider.id)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cash has already been collected for this order.")

    payment = db.scalar(select(Payment).where(Payment.order_id == order.id))
    if payment is None:
        payment = Payment(user_id=order.user_id, order_id=order.id, provider=PaymentProvider.COD, amount=order.total)
        db.add(payment)
        try:
            db.flush()
        except IntegrityError:
            # Two near-simultaneous collect calls for the same order both
            # saw no existing payment — uq_payments_order_id lets exactly
            # one insert win; fall back to the winner's row.
            db.rollback()
            payment = db.scalar(select(Payment).where(Payment.order_id == order.id))

    collected_at = datetime.now(UTC)
    # amount is always order.total, re-read from the row we just loaded —
    # never taken from the request, which has no amount field to begin with.
    payment.amount = order.total
    payment.provider = PaymentProvider.COD
    payment.payment_status = PaymentStatus.PAID
    payment.collected_by_rider_id = rider.id
    payment.collected_at = collected_at

    order.payment_status = "paid"
    order.is_paid = True

    # Financial Ledger Validation (Phase 30) — the collection's own
    # permanent record, independent of the mutable Payment row above (see
    # CodCollection's own docstring). uq_cod_collections_payment_id makes
    # a genuine double-insert for the same payment a database-level
    # impossibility, not just something the is_paid guard above happens
    # to prevent today.
    db.add(CodCollection(
        payment_id=payment.id, order_id=order.id, rider_id=rider.id,
        amount=order.total, collected_at=collected_at,
    ))

    # Admin Portal Phase 20 — "COD settlement due". Mirrors admin_cod.py's
    # own collected-minus-remitted formula inline rather than through a
    # shared cross-module helper, matching this project's already-accepted
    # tolerance for this exact kind of small duplication (see Phase 19).
    collected = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), Decimal("0.00"))).where(
            Payment.provider == PaymentProvider.COD, Payment.collected_by_rider_id == rider.id
        )
    ) or Decimal("0.00")
    remitted = db.scalar(
        select(func.coalesce(func.sum(RiderSettlement.amount), Decimal("0.00"))).where(
            RiderSettlement.rider_id == rider.id, RiderSettlement.settlement_type == SettlementType.REMITTANCE
        )
    ) or Decimal("0.00")
    if (collected - remitted) >= COD_SETTLEMENT_DUE_THRESHOLD:
        notify_admins(
            db, NotificationType.COD_SETTLEMENT_DUE, "COD settlement due",
            f"{rider.name} has an outstanding COD balance of {collected - remitted:.2f} awaiting settlement.",
        )

    db.commit()
    db.refresh(payment)

    return CodCollectionRead(
        order_id=order.id,
        payment_id=payment.id,
        amount=payment.amount,
        payment_status=payment.payment_status,
        collected_by_rider_id=rider.id,
        collected_at=collected_at,
    )


def complete_delivery(db: Session, rider: User, order_id: UUID) -> Order:
    """OUT_FOR_DELIVERY -> DELIVERED — the final step of the granular
    rider-driven delivery lifecycle (Phases 10-17).

    "Do not allow arbitrary delivery completion" is enforced by refusing to
    proceed unless every one of the following already holds:

    - Correct assignment / correct order / rider authorization: all three
      come for free from get_rider_delivery_or_404, which only ever returns
      an order whose Order.rider_id is this exact rider — anyone else's
      order, or an unclaimed one, is a 404, never a 403 (same
      never-leak-existence pattern used by every other lookup in this
      module).
    - Delivery state: the order must actually be OUT_FOR_DELIVERY. Trying
      to complete before that is a 409, not a silent no-op.
    - COD state when applicable: a Cash on Delivery order must already be
      marked is_paid — i.e. the rider has already gone through the explicit
      cod-collect step (Phase 16) — before it can be marked delivered. A
      rider can no longer complete a COD delivery without first recording
      that they actually collected the cash.
    - Rider still approved: Phase 25 — a rider suspended after accepting
      this delivery cannot finish it either.

    Phase 28 — idempotent retry: a second completion call once the order is
    already DELIVERED returns it as success (a lost-response retry), not a
    409 — the only genuinely invalid case is trying to complete from any
    OTHER non-OUT_FOR_DELIVERY state, which still 409s below.
    """
    order = get_rider_delivery_or_404(db, rider, order_id)
    if order.status == OrderStatus.DELIVERED:
        return order
    assert_rider_approved(db, rider)

    if order.status != OrderStatus.OUT_FOR_DELIVERY:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot mark delivered — order is currently {order.status.value}.",
        )
    if order.payment_method == "cod" and not order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Collect the cash before marking this delivery complete.",
        )

    try:
        transition_order_status(db, order, OrderStatus.DELIVERED, f"Delivered by rider {rider.name}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    assignment, existed_before = _get_or_create_assignment(db, order.id, rider.id)
    if existed_before:
        _transition_assignment_status(assignment, AssignmentStatus.DELIVERED, idempotent=True)
    else:
        assignment.status = AssignmentStatus.DELIVERED
    assignment.delivered_at = datetime.now(UTC)
    record_delivery_fee_earning(db, rider.id, order)
    db.commit()
    db.refresh(order)
    return order
