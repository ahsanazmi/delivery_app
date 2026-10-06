"""Notifications & Communication System Phase 11 — Rider Notification
Center.

Proves the three genuinely new hooks this phase wires, each a real gap
found by tracing this phase's own checklist against the actual code:
a rider reassigned away from a delivery (a real "order change" that
previously notified nobody but the audit log), a document's individual
approval/rejection outcome (the rider was previously only ever told
their document was *submitted*, never the result), and a rider-facing
copy of the COD-settlement-due alert (previously admin-only).
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.rider_document import DocumentVerificationStatus, RiderDocument
from app.services.addresses import create_address
from app.services.admin_riders import approve_admin_rider_document, reject_admin_rider_document
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import admin_reassign_rider, assign_rider_to_order, create_order, transition_order_status
from app.services.rider_deliveries import COD_SETTLEMENT_DUE_THRESHOLD, collect_cod_payment


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _online_rider(db, *, email, phone):
    rider = User(name="Rider", email=email, password_hash="x", role=UserRole.RIDER, phone=phone)
    db.add(rider)
    db.commit()
    partner = DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
    db.add(partner)
    db.commit()
    return rider


def _restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def test_rider_reassigned_away_is_notified(db):
    rider_a = _online_rider(db, email="reassign-a@example.com", phone="8900000001")
    rider_b = _online_rider(db, email="reassign-b@example.com", phone="8900000002")
    customer = User(name="Cust", email="reassign-cust@example.com", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id)
    for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
        transition_order_status(db, order, target)
    assign_rider_to_order(db, order, rider_a.id)

    admin = User(name="Admin", email="reassign-admin@example.com", password_hash="x", role=UserRole.ADMIN, phone="8900000003")
    db.add(admin)
    db.commit()

    admin_reassign_rider(db, admin, order.id, rider_b.id, reason="rider A unreachable")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider_a.id, Notification.type == NotificationType.DELIVERY_UPDATED)
    )
    assert notification is not None
    assert notification.order_id == order.id

    # The new rider must not have gotten this "reassigned away" notice —
    # it's specifically for the outgoing rider.
    rider_b_notification = db.scalar(
        select(Notification).where(Notification.user_id == rider_b.id, Notification.type == NotificationType.DELIVERY_UPDATED)
    )
    assert rider_b_notification is None


def test_document_approval_notifies_the_rider(db):
    rider = _online_rider(db, email="doc-approve@example.com", phone="8900000004")
    admin = User(name="Admin", email="doc-admin@example.com", password_hash="x", role=UserRole.ADMIN, phone="8900000005")
    db.add(admin)
    db.commit()
    document = RiderDocument(
        rider_id=rider.id, document_type="DRIVING_LICENSE", document_url="https://example.com/dl.jpg",
        verification_status=DocumentVerificationStatus.PENDING,
    )
    db.add(document)
    db.commit()

    approve_admin_rider_document(db, rider.id, document.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.DOCUMENT_APPROVED)
    )
    assert notification is not None
    assert "Driving License" in notification.body


def test_document_rejection_notifies_the_rider_with_the_reason(db):
    rider = _online_rider(db, email="doc-reject@example.com", phone="8900000006")
    admin = User(name="Admin", email="doc-admin-2@example.com", password_hash="x", role=UserRole.ADMIN, phone="8900000007")
    db.add(admin)
    db.commit()
    document = RiderDocument(
        rider_id=rider.id, document_type="IDENTITY_DOCUMENT", document_url="https://example.com/id.jpg",
        verification_status=DocumentVerificationStatus.PENDING,
    )
    db.add(document)
    db.commit()

    reject_admin_rider_document(db, rider.id, document.id, "Photo is blurry")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.DOCUMENT_REJECTED)
    )
    assert notification is not None
    assert "Photo is blurry" in notification.body


def test_cod_settlement_due_notifies_both_the_admin_and_the_rider(db):
    rider = _online_rider(db, email="cod-rider-notif@example.com", phone="8900000008")
    admin = User(name="Admin", email="cod-admin-notif@example.com", password_hash="x", role=UserRole.ADMIN, phone="8900000009")
    db.add(admin)
    db.commit()
    customer = User(name="Cust", email="cod-cust-notif@example.com", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()

    order = Order(
        user_id=customer.id, rider_id=rider.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(uuid.uuid4()), restaurant_name="R", order_number=f"ORD-{uuid.uuid4().hex[:20]}",
        status=OrderStatus.OUT_FOR_DELIVERY, subtotal=COD_SETTLEMENT_DUE_THRESHOLD, delivery_fee=Decimal("0.00"),
        total=COD_SETTLEMENT_DUE_THRESHOLD, payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()

    collect_cod_payment(db, rider, order.id)

    admin_notification = db.scalar(
        select(Notification).where(Notification.user_id == admin.id, Notification.type == NotificationType.COD_SETTLEMENT_DUE)
    )
    rider_notification = db.scalar(
        select(Notification).where(Notification.user_id == rider.id, Notification.type == NotificationType.COD_SETTLEMENT_DUE)
    )
    assert admin_notification is not None
    assert rider_notification is not None
    # Distinct, role-appropriate copy — not the same third-person string
    # just re-addressed.
    assert "You have an outstanding COD balance" in rider_notification.body
    assert rider.name not in rider_notification.body
