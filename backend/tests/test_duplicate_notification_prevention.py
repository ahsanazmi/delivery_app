"""Notifications & Communication System Phase 30 — Duplicate Notification
Prevention.

This codebase doesn't use a bolt-on "event_id + recipient + type" key at
the Notification layer — it achieves the same guarantee more
fundamentally: every notify_* function only ever fires as a side effect
of a business-state transition that is itself already guarded against
repeating (an atomic conditional UPDATE, a uniqueness constraint, an
explicit valid-from-state check). If the state can't change twice, the
notification that follows it can't fire twice either. This has already
been proven for the highest-traffic paths in earlier phases:

- webhook retry -> tests/test_payment_webhooks.py's own
  "*_is_idempotent_on_replay" tests (event_id uniqueness, Phase 18)
- order-placement retry -> test_customer_order_lifecycle_notifications.py
  (Phase 18's own cart-claim)
- order-status-transition retry -> same file (Phase 24's atomic UPDATE)
- RIDER_APPROACHING re-evaluation on every GPS update ->
  test_rider_approaching_notification.py's own
  test_never_fires_a_second_time_for_the_same_order (a durable check
  against the Notification table itself, not an in-process flag)

This file covers the remaining paths this phase's own audit found were
never explicitly asserted: a rider's own idempotent COD-collection retry,
an admin double-approving an already-reviewed document, and an admin
retrying a rider reassignment that already happened.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.restaurant import Restaurant
from app.models.rider_document import DocumentType
from app.models.user import User, UserRole
from app.db.base import Base
from app.schemas.rider_document import RiderDocumentCreate
from app.services.addresses import create_address
from app.services.admin_riders import approve_admin_rider_document
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import admin_reassign_rider, assign_rider_to_order, create_order, transition_order_status
from app.services.rider_deliveries import accept_delivery, collect_cod_payment, pickup_delivery, start_delivery
from app.services.rider_documents import create_rider_document
from fastapi import HTTPException


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant(db, tag="p30"):
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


def _place_order(db, restaurant, *, customer_email="customer-p30@example.com"):
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


def test_retried_cod_collection_by_the_same_rider_never_sends_a_second_notification(db):
    restaurant = _restaurant(db, "codretry")
    order = _place_order(db, restaurant, customer_email="cust-codretry@example.com")
    rider = _approved_rider(db, email="rider-codretry@example.com", phone="9800000040")

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)
    pickup_delivery(db, rider, order.id)
    start_delivery(db, rider, order.id)

    collect_cod_payment(db, rider, order.id)
    collect_cod_payment(db, rider, order.id)  # a lost-response retry, same rider

    notifications = db.scalars(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.COD_COLLECTED)
    ).all()
    assert len(notifications) == 1


def test_double_approving_an_already_approved_document_never_sends_a_second_notification(db):
    rider = _approved_rider(db, email="rider-docretry@example.com", phone="9800000041")
    document = create_rider_document(
        db, rider.id,
        RiderDocumentCreate(document_type=DocumentType.DRIVING_LICENSE, document_url="https://example.com/dl.jpg"),
    )

    approve_admin_rider_document(db, rider.id, document.id)
    with pytest.raises(HTTPException) as exc_info:
        approve_admin_rider_document(db, rider.id, document.id)  # a double-click retry
    assert exc_info.value.status_code == 409

    notifications = db.scalars(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.DOCUMENT_APPROVED)
    ).all()
    assert len(notifications) == 1


def test_retrying_an_identical_rider_reassignment_never_sends_a_second_notification(db):
    restaurant = _restaurant(db, "reassignretry")
    order = _place_order(db, restaurant, customer_email="cust-reassignretry@example.com")
    original_rider = _approved_rider(db, email="rider-reassign-orig@example.com", phone="9800000042")
    new_rider = _approved_rider(db, email="rider-reassign-new@example.com", phone="9800000043")
    admin = User(name="Admin", email="admin-p30@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()

    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    assign_rider_to_order(db, order, original_rider.id)
    db.commit()

    admin_reassign_rider(db, admin, order.id, new_rider.id, reason="original rider went offline")
    with pytest.raises(HTTPException) as exc_info:
        # A retried identical request — the order is now already assigned
        # to new_rider, so "reassigning" it to the same rider again is
        # correctly rejected before any notification is raised again.
        admin_reassign_rider(db, admin, order.id, new_rider.id, reason="original rider went offline")
    assert exc_info.value.status_code == 409

    notifications = db.scalars(
        select(Notification).where(Notification.order_id == order.id, Notification.type == NotificationType.DELIVERY_UPDATED)
    ).all()
    # One row for the outgoing rider (notify_rider_reassigned_away) + one
    # for the restaurant (notify_restaurant_delivery_exception) — exactly
    # two, from the one genuine reassignment, never four from a retry.
    assert len(notifications) == 2
