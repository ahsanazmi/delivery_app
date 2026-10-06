"""Notifications & Communication System Phase 19 — Restaurant Order
Notifications.

"New order" and "customer cancellation" were already covered by Phase 12
(notify_restaurant_new_order / notify_restaurant_order_cancelled) — not
re-tested here. This file covers the two genuine gaps this phase's own
audit found: "payment confirmation where relevant" (online orders only —
restaurant_dashboard.py's own queue already hides an unpaid razorpay
order from the owner, so payment confirmation is the moment it becomes
actionable) and "delivery exception" (an admin-forced rider reassignment
— the one real delivery-exception path this codebase has today).
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
from app.models.payment import Payment, PaymentProvider as PaymentProviderEnum
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import admin_reassign_rider, assign_rider_to_order, create_order, transition_order_status
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant_with_owner(db, *, owner_email="owner-p19@example.com"):
    owner_phone = f"98{abs(hash(owner_email)) % 10**8:08d}"
    owner = User(name="Owner", email=owner_email, phone=owner_phone, password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Notif Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return owner, restaurant


def _place_order(db, restaurant, *, customer_email="customer-p19@example.com", payment_method="cod"):
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
    return create_order(db, customer, address.id, payment_method=payment_method)


def _approved_rider(db, *, email, phone):
    rider = User(name="Rider", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()
    return rider


class FakeProvider(PaymentProvider):
    """Self-contained — only what the payment-success path needs, same
    convention every other test file in this suite already follows."""

    name = "fake"

    def __init__(self):
        self._order_id = None
        self._amount = None

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._order_id = f"order_fake_{receipt}"
        self._amount = amount
        return ProviderOrder(provider_order_id=self._order_id, amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True  # this file only exercises the success path

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=self._order_id,
            status="captured", amount=self._amount, currency="INR",
        )

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=self._amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_fake", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def test_online_payment_confirmation_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-payok@example.com")
    order = _place_order(db, restaurant, customer_email="cust-payok@example.com")

    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p19_ok", signature="valid",
    )

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.PAYMENT_UPDATE)
    )
    assert notification is not None
    assert notification.role == UserRole.RESTAURANT_OWNER
    assert notification.order_id == order.id
    assert "confirmed" in notification.body.lower()


def test_cod_orders_never_generate_a_payment_confirmation_alert_for_the_restaurant(db):
    """"Where relevant" deliberately excludes COD — cash is collected near
    the end of delivery, long after the restaurant has already prepared
    and handed off the food; a payment-confirmed alert then would be
    noise, not something they can still act on."""
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-cod@example.com")
    order = _place_order(db, restaurant, customer_email="cust-cod@example.com", payment_method="cod")

    for target in (
        OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP,
        OrderStatus.RIDER_ASSIGNED, OrderStatus.PICKED_UP, OrderStatus.OUT_FOR_DELIVERY, OrderStatus.DELIVERED,
    ):
        transition_order_status(db, order, target)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.PAYMENT_UPDATE)
    )
    assert notification is None


def test_rider_reassignment_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-reassign@example.com")
    order = _place_order(db, restaurant, customer_email="cust-reassign@example.com")
    for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
        transition_order_status(db, order, target)

    original_rider = _approved_rider(db, email="rider-orig@example.com", phone="9800000001")
    new_rider = _approved_rider(db, email="rider-new@example.com", phone="9800000002")
    assign_rider_to_order(db, order, original_rider.id)
    db.commit()

    admin = User(name="Admin", email="admin-p19@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add(admin)
    db.commit()

    admin_reassign_rider(db, admin, order.id, new_rider.id, reason="original rider went offline")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.DELIVERY_UPDATED)
    )
    assert notification is not None
    assert notification.role == UserRole.RESTAURANT_OWNER
    assert notification.order_id == order.id
