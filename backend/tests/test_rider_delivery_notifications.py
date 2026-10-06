"""Notifications & Communication System Phase 20 — Rider Delivery
Notifications.

"Assignment cancelled" / "customer cancellation" and "order changed"
were already wired by earlier phases (the DELIVERY_CANCELLED branch
inside notify_order_status_change, and notify_rider_reassigned_away from
Phase 11) — confirmed here, not re-derived. "Operational warning"
(COD_SETTLEMENT_DUE, ACCOUNT_SUSPENDED, DOCUMENT_REJECTED) was already
covered by Phase 11 and has its own test file. The one genuine gap this
phase's own audit found is "new assignment": a rider an admin assigns
directly (never via the self-service accept_delivery flow) previously
got no notification telling them they now owned a delivery at all.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import admin_assign_rider_to_order, create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant(db, tag="p20"):
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, *, customer_email="customer-p20@example.com"):
    customer = User(name="Cust", email=customer_email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    from app.models.product import Product

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _approved_rider(db, *, email, phone):
    rider = User(name="Rider", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    return rider


def test_admin_direct_assignment_notifies_the_rider(db):
    restaurant = _restaurant(db, "assign")
    order = _place_order(db, restaurant, customer_email="cust-assign@example.com")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    rider = _approved_rider(db, email="rider-assign@example.com", phone="9800000010")
    admin = User(name="Admin", email="admin-p20@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()

    admin_assign_rider_to_order(db, admin, order, rider.id, reason="manual dispatch")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.NEW_DELIVERY)
    )
    assert notification is not None
    assert notification.role == UserRole.RIDER
    assert notification.order_id == order.id
    assert "assigned" in notification.body.lower()


def test_self_service_accept_never_duplicates_the_new_assignment_notification(db):
    """Phase 11's own rule still holds: a rider's own synchronous accept
    action gets no notification of its own — accept_delivery never calls
    assign_rider_to_order at all, so notify_rider_new_assignment can
    never fire for it."""
    restaurant = _restaurant(db, "selfaccept")
    order = _place_order(db, restaurant, customer_email="cust-selfaccept@example.com")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    rider = _approved_rider(db, email="rider-selfaccept@example.com", phone="9800000011")
    accept_delivery(db, rider, order.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.NEW_DELIVERY)
    )
    assert notification is None


def test_order_cancelled_after_assignment_notifies_the_assigned_rider(db):
    """Confirms the "assignment cancelled" / "customer cancellation"
    coverage that already existed before this phase (notify_order_status_
    change's own DELIVERY_CANCELLED branch) — not a new hook, but never
    explicitly asserted from this phase's own angle until now."""
    restaurant = _restaurant(db, "cancelassigned")
    order = _place_order(db, restaurant, customer_email="cust-cancelassigned@example.com")
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)

    rider = _approved_rider(db, email="rider-cancelassigned@example.com", phone="9800000012")
    accept_delivery(db, rider, order.id)

    transition_order_status(db, order, OrderStatus.CANCELLED, "customer changed their mind")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.DELIVERY_CANCELLED)
    )
    assert notification is not None
    assert notification.order_id == order.id
