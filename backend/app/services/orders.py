import logging
import secrets
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.config import settings
from app.models.cart import Cart
from app.models.delivery_assignment import AssignmentStatus, DeliveryAssignment
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import NotificationType
from app.models.order import Order, OrderItem, OrderStatus, OrderStatusHistory
from app.models.payment import Payment, PaymentStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.cart import add_item, clear_cart, get_cart_for_user
from app.services.checkout import validate_checkout
from app.services.commissions import compute_effective_commission
from app.services.coupons import record_coupon_redemption
from app.services.admin_audit_log import record_admin_audit_log
from app.services.notifications import notify_admins, notify_order_placed, notify_order_status_change, notify_riders_of_new_delivery
from app.services.restaurant_dashboard import READY_STATUSES
from app.services.tracking_snapshot import build_tracking_snapshot, to_tracking_response
from app.ws.manager import manager

logger = logging.getLogger(__name__)

# The restaurant-owner order list's filter buckets. "ready" reuses the exact
# same status group as the Phase 2 dashboard's "ready" stat card, for
# consistency; "confirmed" and "preparing" are kept separate here (unlike the
# dashboard's merged "preparing" card) since an owner managing an incoming
# order queue genuinely wants to tell "accepted, not started" apart from
# "actively cooking." "cancelled" folds in REJECTED too — there's no separate
# filter option for it, and both are terminal/non-fulfilled outcomes.
RESTAURANT_ORDER_STATUS_FILTERS: dict[str, tuple[OrderStatus, ...]] = {
    "pending": (OrderStatus.PLACED,),
    "confirmed": (OrderStatus.CONFIRMED,),
    "preparing": (OrderStatus.PREPARING,),
    "ready": READY_STATUSES,
    "completed": (OrderStatus.DELIVERED,),
    "cancelled": (OrderStatus.CANCELLED, OrderStatus.REJECTED),
}

# The single source of truth for which status can move to which. Every status
# mutation (customer cancel, rider pickup/deliver, admin override) must go
# through transition_order_status() below rather than assigning order.status
# directly, so this table is the only place "what's a legal move" is decided.
VALID_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PLACED: {OrderStatus.CONFIRMED, OrderStatus.REJECTED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.PREPARING, OrderStatus.RIDER_ASSIGNED, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.READY_FOR_PICKUP, OrderStatus.RIDER_ASSIGNED, OrderStatus.CANCELLED},
    OrderStatus.READY_FOR_PICKUP: {OrderStatus.RIDER_ASSIGNED, OrderStatus.CANCELLED},
    OrderStatus.RIDER_ASSIGNED: {OrderStatus.PICKED_UP, OrderStatus.CANCELLED},
    OrderStatus.PICKED_UP: {OrderStatus.OUT_FOR_DELIVERY},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: set(),
    OrderStatus.CANCELLED: set(),
    OrderStatus.REJECTED: set(),
}

# Customers may only cancel their own order themselves before the restaurant has
# started preparing it. Later-stage cancellation (still technically reachable
# per VALID_TRANSITIONS, for staff/admin use) is not something the customer can
# self-serve.
CUSTOMER_CANCELLABLE_STATUSES = {OrderStatus.PLACED, OrderStatus.CONFIRMED}

# Admin Portal Phase 11 — every status this table lets move to CANCELLED is
# exactly the set an admin may cancel from (wider than the customer's own
# set above, matching this project's long-standing comment that later-stage
# cancellation is "for staff/admin use"). Derived from VALID_TRANSITIONS
# itself rather than hand-duplicated, so the two can never drift apart.
ADMIN_CANCELLABLE_STATUSES = {
    order_status for order_status, targets in VALID_TRANSITIONS.items() if OrderStatus.CANCELLED in targets
}

# Reassigning to a different rider only makes real-world sense before the
# food has physically left the restaurant with the current rider — once
# PICKED_UP, the new rider doesn't have the food, so there's nothing to
# reassign. This is deliberately narrower than "any order with a rider."
ADMIN_REASSIGNABLE_STATUSES = {OrderStatus.RIDER_ASSIGNED}


def _next_order_number() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    suffix = secrets.token_hex(3).upper()
    return f"ORD-{stamp}-{suffix}"


def _add_status_history(db: Session, order: Order, status: OrderStatus, note: str | None = None) -> OrderStatusHistory:
    history = OrderStatusHistory(order_id=order.id, status=status, note=note)
    db.add(history)
    db.flush()
    return history


def _settle_cod_payment_on_delivery(db: Session, order: Order) -> None:
    """Cash on Delivery is only ever marked paid here — as a side effect of a
    rider/admin-driven DELIVERED transition. There is no customer-reachable
    path that can flip this; customers can't call transition_order_status
    with DELIVERED at all (see VALID_TRANSITIONS + who's allowed to call it)."""
    if order.payment_method != "cod":
        return
    order.payment_status = "paid"
    order.is_paid = True
    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    if payment:
        payment.payment_status = PaymentStatus.PAID


def _cancel_delivery_assignment(db: Session, order: Order) -> None:
    """Phase 24: an order cancelled while a rider still had a non-terminal
    assignment on it must not leave that assignment stuck at whatever step
    it was on (e.g. PICKED_UP) forever — that would make the assignment's
    own state machine lie about a delivery that no longer exists. This is a
    system-triggered side effect of order cancellation, not a rider action,
    so it deliberately bypasses rider_deliveries.py's rider-facing
    ASSIGNMENT_VALID_TRANSITIONS choke point (calling into that module from
    here would also be a circular import — rider_deliveries.py already
    imports transition_order_status from this module) and instead moves the
    assignment directly, from any of its own non-terminal states."""
    if order.rider_id is None:
        return
    assignment = db.scalar(
        select(DeliveryAssignment).where(
            DeliveryAssignment.order_id == order.id, DeliveryAssignment.rider_id == order.rider_id
        )
    )
    if assignment is None or assignment.status in (
        AssignmentStatus.DELIVERED,
        AssignmentStatus.REJECTED,
        AssignmentStatus.CANCELLED,
    ):
        return
    assignment.status = AssignmentStatus.CANCELLED
    assignment.cancelled_at = datetime.now(UTC)


def _broadcast_tracking_update(db: Session, order: Order) -> None:
    """Push a fresh tracking snapshot to any customer currently watching this
    order's WebSocket room. A no-op if nobody's connected."""
    snapshot = build_tracking_snapshot(db, order)
    manager.broadcast(order.id, to_tracking_response(snapshot).model_dump(mode="json"))


def transition_order_status(db: Session, order: Order, new_status: OrderStatus, note: str | None = None) -> Order:
    """The single choke point for every order status mutation. Commits and
    broadcasts the change itself, so every caller (customer cancel, rider
    pickup/deliver, admin override) gets live tracking for free instead of
    having to remember to wire it up at each call site.

    Database Transaction Testing (Phase 24) — live-proved that two genuinely
    concurrent calls advancing the SAME order from the SAME status (e.g. a
    rider double-tapping "complete delivery" from two devices, or a lost-
    response retry racing the original request) both read the same stale
    `order.status` before either commits, both pass the VALID_TRANSITIONS
    check above, and — since this used to be a plain `order.status =
    new_status` attribute assignment — both proceeded to run every side
    effect below (including complete_delivery's record_delivery_fee_earning,
    which has no existence check), crediting the rider twice for one
    delivery. Guarded the same way accept_delivery() guards its rider claim:
    an atomic conditional UPDATE whose WHERE clause re-checks the status
    against the database's committed state at the moment it acquires the
    row's write lock, not against whatever this Python object loaded earlier.
    The loser's UPDATE matches zero rows once the winner commits, so it
    raises the same ValueError a genuinely invalid transition would — every
    caller already converts that to a clean 409, so no caller needs to
    change."""
    previous_status = order.status
    allowed = VALID_TRANSITIONS.get(previous_status, set())
    if new_status not in allowed:
        # Logging & Error Handling (Phase 26) — the single choke point for
        # every order-status mutation is also the single place an invalid
        # transition is logged, regardless of which portal/role attempted it.
        logger.warning(
            "Order error: rejected invalid transition for order %s (%s -> %s)",
            order.id, previous_status.value, new_status.value,
        )
        raise ValueError(f"Cannot move an order from {previous_status.value} to {new_status.value}")
    result = db.execute(
        update(Order).where(Order.id == order.id, Order.status == previous_status).values(status=new_status)
    )
    if result.rowcount == 0:
        db.rollback()
        logger.warning(
            "Order error: order %s status changed concurrently, rejected transition to %s", order.id, new_status.value
        )
        raise ValueError(
            f"Cannot move an order from {previous_status.value} to {new_status.value} "
            "— another request already changed this order's status."
        )
    db.refresh(order)
    _add_status_history(db, order, new_status, note)
    notify_order_status_change(db, order, new_status)
    if new_status == OrderStatus.DELIVERED:
        _settle_cod_payment_on_delivery(db, order)
    if new_status == OrderStatus.READY_FOR_PICKUP:
        notify_riders_of_new_delivery(db, order)
    if new_status == OrderStatus.CANCELLED:
        _cancel_delivery_assignment(db, order)
    if new_status in (OrderStatus.CANCELLED, OrderStatus.REJECTED):
        # Admin Portal Phase 20 — "Order issue": something went wrong with
        # this order, worth an admin's attention, regardless of who or what
        # triggered the cancellation/rejection.
        notify_admins(
            db, NotificationType.ORDER_ISSUE, "Order issue",
            f"Order {order.order_number} was {new_status.value}.", order_id=order.id,
        )
    db.commit()
    db.refresh(order)
    _broadcast_tracking_update(db, order)
    return order


def create_order(
    db: Session,
    user: User,
    address_id: UUID,
    payment_method: str = "cod",
    delivery_instructions: str | None = None,
) -> Order:
    """Create an order from the customer's server-side cart.

    Everything that matters (restaurant, items, prices, delivery fee, tax,
    discount, address) is re-derived from the database here — never accepted
    from the client — via the same validation Phase 8's checkout preview uses,
    so an order can't be placed with a stale price or an address that isn't
    the customer's own.
    """
    # Checkout Payment Decision (Phase 6) — the one checkout-time check
    # that isn't about the cart/restaurant/address: refuse to even open an
    # order with a payment method that can't actually be paid right now,
    # rather than creating it and only discovering that later when the
    # separate payment-recording step 503s. Same underlying availability
    # rule list_payment_methods() already surfaces to the checkout screen
    # (that endpoint's own "online" label is a deliberately gateway-
    # agnostic customer-facing name — CustomerOrderCreate.payment_method
    # itself always carries the concrete provider name, "razorpay", so
    # this checks the same RAZORPAY_KEY_ID/SECRET condition directly
    # rather than string-matching against that other vocabulary).
    if payment_method == "razorpay" and not (settings.RAZORPAY_KEY_ID and settings.RAZORPAY_KEY_SECRET):
        raise ValueError("Online payment is not currently available. Please choose Cash on Delivery.")

    validation = validate_checkout(db, user, address_id)
    if not validation["valid"]:
        raise ValueError(" ".join(validation["issues"]))

    cart = validation["cart"]
    restaurant = validation["restaurant"]
    address = validation["address"]

    try:
        # Retry & Idempotency Integration — a double "Place Order" tap or a
        # client retry after a timeout can put two of these calls in flight
        # for the same customer at once; validate_checkout above is
        # read-mostly and safe to run concurrently, but nothing has claimed
        # the cart yet. This atomic conditional UPDATE is the actual guard:
        # it only succeeds if cart.restaurant_id is still set (i.e. no
        # concurrent call has already claimed this exact cart), mirroring
        # accept_delivery()'s conditional-UPDATE pattern.
        #
        # Database Transaction Testing (Phase 24) — deliberately NOT
        # committed here on its own. An UPDATE acquires its row lock the
        # moment it executes, before any commit — a concurrent second
        # claim attempt on the same cart still blocks until this
        # transaction's outcome (commit *or* rollback) is known, so the
        # concurrency guarantee holds either way. Committing this claim
        # separately from the rest of order creation would let it survive
        # a later failure in this same function (commission computation,
        # OrderItem creation, coupon redemption, ...) — leaving the cart
        # claimed (restaurant_id cleared) with its items still sitting
        # there and no Order ever created: a customer retrying "Place
        # Order" would then get a false "cart is empty" forever, unable to
        # ever place that order again. Letting the claim live or die with
        # the same commit/rollback as everything else below is what keeps
        # this atomic.
        claim = db.execute(
            update(Cart).where(Cart.id == cart.id, Cart.restaurant_id.is_not(None)).values(restaurant_id=None)
        )
        if claim.rowcount == 0:
            raise ValueError("Your cart is empty.")

        # Admin Portal Phase 17 — computed and snapshotted once, right now,
        # from whatever commission rule applies at this exact moment. Never
        # recomputed later, even if the rule subsequently changes.
        commission = compute_effective_commission(db, restaurant.id, validation["subtotal"])

        order = Order(
            user_id=user.id,
            customer_name=user.name,
            customer_email=user.email,
            customer_phone=user.phone,
            restaurant_id=str(restaurant.id),
            restaurant_name=restaurant.name,
            restaurant_phone=restaurant.phone,
            restaurant_address=restaurant.address,
            order_number=_next_order_number(),
            status=OrderStatus.PLACED,
            payment_method=payment_method,
            subtotal=validation["subtotal"],
            delivery_fee=validation["delivery_fee"],
            tax=validation["tax"],
            discount=validation["discount"],
            total=validation["total"],
            commission_type=commission.commission_type.value if commission else None,
            commission_rate=commission.rate if commission else None,
            commission_amount=commission.amount if commission else None,
            item_count=sum(item.quantity for item in cart.items),
            address_line=address.address_line,
            city=address.city,
            state=address.state,
            postal_code=address.postal_code,
            landmark=address.landmark,
            latitude=address.latitude,
            longitude=address.longitude,
            delivery_instructions=delivery_instructions,
            is_paid=False,
        )
        db.add(order)
        db.flush()

        for item in cart.items:
            db.add(
                OrderItem(
                    order_id=order.id,
                    product_id=str(item.product_id),
                    restaurant_id=str(item.restaurant_id),
                    product_name=item.product_name,
                    unit_price=item.unit_price,
                    quantity=item.quantity,
                )
            )

        _add_status_history(db, order, OrderStatus.PLACED, "Order placed")
        notify_order_placed(db, order)
        if validation.get("coupon_id"):
            record_coupon_redemption(db, validation["coupon_id"], user.id, order.id)
        clear_cart(db, cart)
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(order)
    return order


def list_user_orders(
    db: Session,
    user_id: UUID,
    *,
    status_filter: OrderStatus | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Order]:
    # Performance Baseline (Phase 25) — OrderRead (this list's response
    # schema) serializes both .items and .status_history for every order;
    # without eager loading, each one is a separate lazy-loaded query per
    # order (up to `limit`, capped at 100/page) — a genuine N+1, up to ~200
    # extra round trips for one page. selectinload batches each relationship
    # into one extra query total, regardless of how many orders are on the
    # page.
    query = (
        db.query(Order)
        .options(selectinload(Order.items), selectinload(Order.status_history))
        .filter(Order.user_id == user_id)
    )
    if status_filter is not None:
        query = query.filter(Order.status == status_filter)
    if date_from is not None:
        query = query.filter(Order.created_at >= date_from)
    if date_to is not None:
        query = query.filter(Order.created_at <= date_to)
    return list(query.order_by(Order.created_at.desc()).offset(offset).limit(limit).all())


def get_user_order(db: Session, user_id: UUID, order_id: UUID) -> Order | None:
    return db.query(Order).filter(Order.user_id == user_id, Order.id == order_id).first()


def cancel_order(db: Session, user_id: UUID, order_id: UUID, reason: str | None = None) -> Order:
    order = get_user_order(db, user_id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status not in CUSTOMER_CANCELLABLE_STATUSES:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order cannot be cancelled at this stage")
    order.cancelled_reason = reason
    try:
        transition_order_status(db, order, OrderStatus.CANCELLED, reason or "Cancelled by customer")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def assign_rider_to_order(db: Session, order: Order, rider_id: UUID) -> Order:
    """The generic, unaudited core of "attach a rider to this order" — used
    directly as a test-setup helper across the wider test suite (rider
    dashboard/tracking/pickup/etc. tests that need *an* assigned order and
    aren't testing admin behavior at all), so its signature stays exactly
    as it always has. admin_assign_rider_to_order below wraps this with
    the admin-specific audit trail; never add admin/reason params here
    directly, or every one of those unrelated callers breaks."""
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider is invalid")
    order.rider_id = rider_id
    try:
        transition_order_status(db, order, OrderStatus.RIDER_ASSIGNED, f"Assigned to rider {rider.name}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def _assert_rider_assignable_by_admin(db: Session, rider: User) -> None:
    """Rider Assignment Integration — an admin's direct assignment must be
    held to the same standing the self-service accept flow already
    requires (see rider_service.get_online_eligibility_blocker): a
    suspended, unapproved/pending/rejected, or deactivated rider account
    must never end up as an order's rider_id, regardless of which path put
    it there. A missing DeliveryPartner row (never onboarded) is treated
    the same as PENDING, matching get_or_create_delivery_partner's own
    default."""
    if not rider.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider's account is deactivated")
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == rider.id).first()
    if partner is None or partner.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider is not an approved delivery partner")


def admin_assign_rider_to_order(
    db: Session, admin: User, order: Order, rider_id: UUID, reason: str, ip_address: str | None = None
) -> Order:
    """Order State Rule — the admin-facing entry point (see this
    function's only caller in api/v1/admin/orders.py), distinct from the
    generic assign_rider_to_order above precisely so that function's many
    non-admin test callers are never affected by this audit requirement.
    Validates the transition and records the audit entry (flushed, not
    committed) *before* delegating to assign_rider_to_order, so a rejected
    invalid transition never leaves an orphaned log row, and a successful
    one is persisted atomically with it by transition_order_status's own
    commit."""
    rider = db.get(User, rider_id)
    if not rider or rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider is invalid")
    if order.status not in VALID_TRANSITIONS or OrderStatus.RIDER_ASSIGNED not in VALID_TRANSITIONS[order.status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot assign a rider to an order that is {order.status.value}",
        )
    _assert_rider_assignable_by_admin(db, rider)

    record_admin_audit_log(
        db,
        admin_id=admin.id,
        action="order.assign_rider",
        target_type="order",
        target_id=str(order.id),
        reason=reason,
        previous_state="unassigned",
        new_state=str(rider.id),
        ip_address=ip_address,
    )
    return assign_rider_to_order(db, order, rider_id)


def admin_cancel_order(db: Session, admin: User, order_id: UUID, reason: str, ip_address: str | None = None) -> Order:
    """Admin Portal Phase 11's controlled replacement for the removed
    generic "set to any status" endpoint — cancellation is the one
    later-stage transition with a genuinely clear business rule, so it gets
    its own explicit action instead of a bare status setter.

    The audit entry is written (flushed, not committed) *before*
    transition_order_status runs, so its own internal commit — which we
    don't control — persists the log entry and the actual cancellation
    together, atomically. If the pre-check below already rejected an
    invalid state, no audit entry is ever created for an action that never
    happened."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status not in ADMIN_CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel an order that is already {order.status.value}",
        )

    previous_status = order.status
    order.cancelled_reason = reason
    record_admin_audit_log(
        db,
        admin_id=admin.id,
        action="order.cancel",
        target_type="order",
        target_id=str(order.id),
        reason=reason,
        previous_state=previous_status.value,
        new_state=OrderStatus.CANCELLED.value,
        ip_address=ip_address,
    )
    try:
        transition_order_status(db, order, OrderStatus.CANCELLED, f"Cancelled by admin: {reason}")
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def admin_reassign_rider(
    db: Session, admin: User, order_id: UUID, new_rider_id: UUID, reason: str, ip_address: str | None = None
) -> Order:
    """The phase's other named example — replacing an already-assigned
    rider, distinct from assign_rider_to_order (first assignment to an
    unclaimed order). Only valid while the order is still RIDER_ASSIGNED —
    see ADMIN_REASSIGNABLE_STATUSES for why. The outgoing rider's own
    DeliveryAssignment (if they got there via the normal accept flow, not a
    prior admin force-assignment) is closed out via the same mechanism
    order cancellation already uses, so it doesn't sit at ACCEPTED forever
    pointing at an order this rider no longer has."""
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.rider_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This order has no rider assigned yet — use assign-rider instead.",
        )
    if order.status not in ADMIN_REASSIGNABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot reassign the rider once the order is {order.status.value}",
        )
    new_rider = db.get(User, new_rider_id)
    if not new_rider or new_rider.role != UserRole.RIDER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Selected rider is invalid")
    _assert_rider_assignable_by_admin(db, new_rider)
    if new_rider.id == order.rider_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Order is already assigned to this rider")

    previous_rider_id = order.rider_id
    record_admin_audit_log(
        db,
        admin_id=admin.id,
        action="order.reassign_rider",
        target_type="order",
        target_id=str(order.id),
        reason=reason,
        previous_state=str(previous_rider_id),
        new_state=str(new_rider.id),
        ip_address=ip_address,
    )
    _cancel_delivery_assignment(db, order)
    order.rider_id = new_rider.id
    _add_status_history(db, order, order.status, f"Reassigned by admin from rider {previous_rider_id} to {new_rider.name}: {reason}")
    db.commit()
    db.refresh(order)
    return order


RIDER_ORDERS_LIMIT = 100


def list_rider_orders(db: Session, rider_id: UUID) -> list[Order]:
    """Performance Baseline (Phase 25) — this legacy list (superseded for
    new work by rider_history.list_rider_history's paginated, filterable
    version, but still the one GET /rider/orders and rider-mobile's own
    listRiderOrders() actually call) used to run with neither a cap nor
    eager loading: every order this rider has ever been assigned, all-time,
    each one triggering two extra lazy-loaded queries for OrderRead's
    .items/.status_history. Capped the same defensive way admin_dashboard's
    recent-lists already are, and eager-loaded the same way
    list_user_orders now is."""
    return list(
        db.query(Order)
        .options(selectinload(Order.items), selectinload(Order.status_history))
        .filter(Order.rider_id == rider_id)
        .order_by(Order.created_at.desc())
        .limit(RIDER_ORDERS_LIMIT)
        .all()
    )


def reorder_from_order(db: Session, user: User, order_id: UUID) -> dict:
    """Add a past order's items back to the customer's cart.

    Never trusts anything the old order snapshotted — every item is
    re-validated against the live catalog, and priced at today's price, not
    the historical unit_price the order stored. Items that are no longer
    valid (deleted product, disabled, restaurant closed down) are silently
    skipped rather than blocking the whole reorder, and their names are
    reported back so the customer knows what didn't make it in.
    """
    order = get_user_order(db, user.id, order_id)
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if not order.restaurant_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This order has no restaurant to reorder from.")

    restaurant = db.get(Restaurant, UUID(order.restaurant_id))
    if not restaurant or not restaurant.is_active or restaurant.approval_status != ApprovalStatus.APPROVED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This restaurant is no longer available.")

    cart = get_cart_for_user(db, user.id)
    if cart.items and cart.restaurant_id != restaurant.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your cart has items from a different restaurant. Clear your cart before reordering.",
        )

    unavailable_items: list[str] = []
    for item in order.items:
        product = db.scalar(
            select(Product).where(
                Product.id == UUID(item.product_id),
                Product.restaurant_id == restaurant.id,
                Product.is_active.is_(True),
                Product.is_available.is_(True),
            )
        )
        if not product:
            unavailable_items.append(item.product_name)
            continue
        add_item(db, cart, product.id, item.quantity)

    db.refresh(cart)
    return {"cart": cart, "unavailable_items": unavailable_items}


def mask_customer_name(name: str) -> str:
    """"Amit Sharma" -> "A************" — enough for the owner to recognize
    repeat customers across a glance at the incoming-orders list without
    exposing the full name there; the detail view (get_restaurant_order_or_404)
    still shows it in full, since fulfilling the order genuinely needs it."""
    name = name.strip()
    if len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


_ZERO = Decimal("0.00")


def compute_restaurant_financials(order: Order) -> dict:
    """Restaurant Payment Visibility (Phase 28) — Restaurant earning,
    Commission, and Net amount, computed only from this order's own
    frozen commission_amount (snapshotted once, at order-creation time,
    by compute_effective_commission() — see CommissionRule's own
    docstring: "Nothing in this codebase ever re-reads a CommissionRule
    to recompute a historical order's already-stored commission").
    Deliberately never calls compute_effective_commission() or reads
    CommissionRule again here — a commission rate an admin changes after
    this order was placed must never retroactively change what this
    specific order reports having earned. commission_amount is only ever
    None for orders placed before the commission concept existed at all;
    treated as zero commission (never recomputed from today's rule),
    matching the same "old orders keep whatever they actually recorded"
    principle everywhere else in this codebase.

    - restaurant_earning: the gross amount attributable to the food sold
      (order.subtotal) — what the restaurant would keep if there were no
      platform commission at all. Delivery fee and tax are never the
      restaurant's own money, so they're excluded here.
    - commission: the platform's own cut of that subtotal, exactly as
      charged on this order.
    - net_amount: what the restaurant actually nets after commission —
      restaurant_earning minus commission.
    """
    commission = order.commission_amount if order.commission_amount is not None else _ZERO
    restaurant_earning = order.subtotal
    net_amount = restaurant_earning - commission
    return {"restaurant_earning": restaurant_earning, "commission": commission, "net_amount": net_amount}


def list_restaurant_orders(
    db: Session,
    restaurant_id: UUID,
    *,
    status_filter: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[Order]:
    statement = select(Order).where(Order.restaurant_id == str(restaurant_id))
    # Payment Status Synchronization (Phase 16) — the documented rule: the
    # restaurant doesn't receive an online order until its payment is
    # confirmed. Scoped to PLACED specifically — a CANCELLED/REJECTED
    # order (a customer can cancel their own unpaid order; see
    # CUSTOMER_CANCELLABLE_STATUSES) is a dead, informational record with
    # nothing left to act on, so there's no reason to hide it; and an
    # order can't reach CONFIRMED or later at all without is_paid already
    # being true (see accept_order()'s own gate), so this condition is
    # simply never true past PLACED anyway.
    statement = statement.where(
        ~((Order.status == OrderStatus.PLACED) & (Order.payment_method == "razorpay") & (Order.is_paid.is_(False)))
    )
    if status_filter is not None:
        statuses = RESTAURANT_ORDER_STATUS_FILTERS.get(status_filter)
        if statuses is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status filter")
        statement = statement.where(Order.status.in_(statuses))
    statement = statement.order_by(Order.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(statement))


def get_restaurant_order_or_404(db: Session, restaurant_id: UUID, order_id: UUID) -> Order:
    """Scoped to restaurant_id — an order placed at a different restaurant is
    treated as not found, the same "never leak that it exists" pattern used
    for categories and products in Phases 5-6."""
    order = db.scalar(select(Order).where(Order.id == order_id, Order.restaurant_id == str(restaurant_id)))
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def accept_order(db: Session, restaurant_id: UUID, order_id: UUID) -> Order:
    order = get_restaurant_order_or_404(db, restaurant_id, order_id)
    # Payment Status Synchronization (Phase 16) — the documented rule: an
    # online (razorpay) order isn't committed to the kitchen until payment
    # is actually confirmed. It already won't appear in the restaurant's
    # own pending list before then (see list_restaurant_orders() and the
    # dashboard's own pending query) — this is the same rule enforced
    # again at the one place that actually commits food/prep resources,
    # so it holds even against a stale or otherwise-obtained order id, not
    # just at the UI layer. COD is unaffected — cash is collected on
    # delivery, so there's nothing to confirm first.
    if order.payment_method == "razorpay" and not order.is_paid:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This order's online payment hasn't been confirmed yet.",
        )
    try:
        transition_order_status(db, order, OrderStatus.CONFIRMED, "Accepted by restaurant")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def reject_order(db: Session, restaurant_id: UUID, order_id: UUID, reason: str | None = None) -> Order:
    order = get_restaurant_order_or_404(db, restaurant_id, order_id)
    order.cancelled_reason = reason
    try:
        transition_order_status(db, order, OrderStatus.REJECTED, reason or "Rejected by restaurant")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def mark_order_preparing(db: Session, restaurant_id: UUID, order_id: UUID) -> Order:
    order = get_restaurant_order_or_404(db, restaurant_id, order_id)
    try:
        transition_order_status(db, order, OrderStatus.PREPARING, "Restaurant started preparing the order")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order


def mark_order_ready(db: Session, restaurant_id: UUID, order_id: UUID) -> Order:
    order = get_restaurant_order_or_404(db, restaurant_id, order_id)
    try:
        transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP, "Order ready for pickup")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return order
