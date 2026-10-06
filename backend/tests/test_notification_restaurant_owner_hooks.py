"""Notifications & Communication System Phase 12 — Restaurant Owner
Notifications.

Proves the four backend hooks this phase wires, all resolved through
Order.restaurant_id -> Restaurant.owner_id (a real restaurant, not a
stand-in id) and scoped to that owner's own Notification.user_id — the
same IDOR-safe pattern every other role's notifications already use.
"""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import hash_password
from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider as PaymentProviderEnum
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.rider_deliveries import accept_delivery


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _restaurant_with_owner(db, *, owner_email="owner-p12@example.com"):
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


def _place_order(db, restaurant, *, customer_email="customer-p12@example.com"):
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


def test_new_order_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db)
    order = _place_order(db, restaurant)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.RESTAURANT_NEW_ORDER)
    )
    assert notification is not None
    assert notification.order_id == order.id
    assert order.order_number in notification.body


def test_order_cancellation_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-cancel@example.com")
    order = _place_order(db, restaurant, customer_email="cust-cancel@example.com")
    transition_order_status(db, order, OrderStatus.CANCELLED, "customer changed their mind")

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.RESTAURANT_ORDER_CANCELLED)
    )
    assert notification is not None
    assert notification.order_id == order.id


def test_rider_assignment_notifies_the_restaurant_owner_regardless_of_which_path_assigned_it(db):
    """Proves the hook fires from the shared choke point
    (transition_order_status), not a specific caller — exercised here via
    accept_delivery (the self-service rider flow), not the admin-direct
    assign_rider_to_order helper other test files use."""
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-rider@example.com")
    order = _place_order(db, restaurant, customer_email="cust-rider@example.com")
    for target in (OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP):
        transition_order_status(db, order, target)

    rider = User(name="Rider", email="rider-p12@example.com", phone="9800000099", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    from app.models.delivery_partner import ApprovalStatus, DeliveryPartner

    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()

    accept_delivery(db, rider, order.id)

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.RIDER_ASSIGNED)
    )
    assert notification is not None
    assert notification.role == UserRole.RESTAURANT_OWNER


class FakeProvider(PaymentProvider):
    """Minimal — only what the payment-verification-failure path needs
    (this file's own self-contained helper, matching this codebase's
    convention of never importing test helpers across test files)."""

    name = "fake"

    def __init__(self):
        self._order_id: str | None = None
        self._amount: Decimal | None = None

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._order_id = f"order_fake_{receipt}"
        self._amount = amount
        return ProviderOrder(provider_order_id=self._order_id, amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return False  # always invalid — this file only exercises the failure path

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


def test_payment_verification_failure_notifies_the_restaurant_owner(db):
    owner, restaurant = _restaurant_with_owner(db, owner_email="owner-payfail@example.com")
    order = _place_order(db, restaurant, customer_email="cust-payfail@example.com")

    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")

    from app.services.payment.exceptions import PaymentVerificationError

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            db, payment=payment, provider_order_id=payment.razorpay_order_id,
            provider_payment_id="pay_p12_fail", signature="forged",
        )

    notification = db.scalar(
        select(Notification).where(Notification.user_id == owner.id, Notification.type == NotificationType.PAYMENT_UPDATE)
    )
    assert notification is not None
    assert notification.order_id == order.id


def test_restaurant_owner_only_ever_sees_their_own_notifications_over_http(client):
    """This phase's own explicit security requirement, verified against
    the real HTTP endpoint (not just the service function): two separate
    restaurant owners, each with their own order's new-order alert —
    owner A's GET /restaurant/notifications must never include owner B's
    row, and the unread-count must reflect only their own."""
    from app.core.security import create_access_token
    from app.db.session import get_db

    db = next(client.app.dependency_overrides[get_db]())
    owner_a, restaurant_a = _restaurant_with_owner(db, owner_email="owner-http-a@example.com")
    owner_b, restaurant_b = _restaurant_with_owner(db, owner_email="owner-http-b@example.com")
    _place_order(db, restaurant_a, customer_email="cust-http-a@example.com")
    _place_order(db, restaurant_b, customer_email="cust-http-b@example.com")

    headers_a = {"Authorization": f"Bearer {create_access_token(owner_a.id)}"}
    headers_b = {"Authorization": f"Bearer {create_access_token(owner_b.id)}"}

    listed_a = client.get("/api/v1/restaurant/notifications", headers=headers_a).json()
    assert len(listed_a) == 1
    assert listed_a[0]["type"] == "restaurant_new_order"

    count_a = client.get("/api/v1/restaurant/notifications/unread-count", headers=headers_a)
    count_b = client.get("/api/v1/restaurant/notifications/unread-count", headers=headers_b)
    assert count_a.json()["unread_count"] == 1
    assert count_b.json()["unread_count"] == 1

    # Marking owner A's own notification read must never touch owner B's.
    client.post(f"/api/v1/restaurant/notifications/{listed_a[0]['id']}/read", headers=headers_a)
    assert client.get("/api/v1/restaurant/notifications/unread-count", headers=headers_a).json()["unread_count"] == 0
    assert client.get("/api/v1/restaurant/notifications/unread-count", headers=headers_b).json()["unread_count"] == 1

    # Owner B can never mark owner A's notification read by id, either.
    forbidden = client.post(f"/api/v1/restaurant/notifications/{listed_a[0]['id']}/read", headers=headers_b)
    assert forbidden.status_code == 404
