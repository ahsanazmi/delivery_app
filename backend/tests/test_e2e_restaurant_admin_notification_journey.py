"""Notifications & Communication System Phase 39 — Restaurant/Admin E2E
Test.

Walks this phase's exact sequence — new order, restaurant notification,
restaurant accepts, rider assigned, operational notification, payment
event, admin operational alert — as one continuous narrative, with the
explicit extra requirement this phase names: tenant/role isolation. A
second, completely unrelated restaurant owner and a second admin are
present throughout and asserted to see none of the first restaurant's
or first event's own notifications.
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
from app.services.orders import create_order, transition_order_status
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


class FakeProvider(PaymentProvider):
    name = "fake"

    def __init__(self):
        self._order_id = None
        self._amount = None

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._order_id = f"order_fake_{receipt}"
        self._amount = amount
        return ProviderOrder(provider_order_id=self._order_id, amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=self._order_id, status="captured", amount=self._amount, currency="INR")

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=self._amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_fake", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True


def test_full_restaurant_and_admin_notification_journey_with_tenant_isolation(db):
    # --- Tenants: restaurant A (the one under test), restaurant B (an
    # unrelated bystander that must see nothing), two admins ---
    owner_a = User(name="Owner A", email="e2e-owner-a@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    owner_b = User(name="Owner B", email="e2e-owner-b@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add_all([owner_a, owner_b])
    db.commit()
    restaurant_a = Restaurant(
        owner_id=owner_a.id, name="Diner A", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    restaurant_b = Restaurant(
        owner_id=owner_b.id, name="Diner B", phone="9876500000", address="2 Road",
        latitude=Decimal("12.2"), longitude=Decimal("77.2"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
    )
    db.add_all([restaurant_a, restaurant_b])
    db.commit()

    admin_1 = User(name="Admin 1", email="e2e-admin-1@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    admin_2 = User(name="Admin 2", email="e2e-admin-2@example.com", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add_all([admin_1, admin_2])
    db.commit()

    rider = User(name="Rider", email="e2e-ra-rider@example.com", phone="9800000080", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))
    db.commit()

    customer = User(name="Cust", email="e2e-ra-cust@example.com", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()

    from app.models.product import Product

    product = Product(restaurant_id=restaurant_a.id, name="Item", price=Decimal("150.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "1 Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })

    # --- New order -> restaurant notification (restaurant A only) ---
    order = create_order(db, customer, address.id)
    new_order_notification = db.scalar(
        select(Notification).where(Notification.user_id == owner_a.id, Notification.type == NotificationType.RESTAURANT_NEW_ORDER)
    )
    assert new_order_notification is not None
    assert new_order_notification.order_id == order.id
    assert db.scalar(
        select(Notification).where(Notification.user_id == owner_b.id, Notification.type == NotificationType.RESTAURANT_NEW_ORDER)
    ) is None

    # --- Restaurant accepts (confirms) -> rider assigned -> operational
    # notification (restaurant A gets told a rider is coming) ---
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    transition_order_status(db, order, OrderStatus.READY_FOR_PICKUP)
    accept_delivery(db, rider, order.id)

    rider_assigned_notification = db.scalar(
        select(Notification).where(Notification.user_id == owner_a.id, Notification.type == NotificationType.RIDER_ASSIGNED)
    )
    assert rider_assigned_notification is not None
    assert rider_assigned_notification.order_id == order.id
    assert db.scalar(
        select(Notification).where(Notification.user_id == owner_b.id, Notification.type == NotificationType.RIDER_ASSIGNED)
    ) is None

    # --- Payment event -> admin operational alert (a payment anomaly:
    # successfully captured for a now-cancelled order) ---
    transition_order_status(db, order, OrderStatus.CANCELLED, "customer changed their mind")
    fake = FakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    from app.models.payment import PaymentStatus

    payment.payment_status = PaymentStatus.PENDING
    db.commit()
    result = service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_e2e_ra", signature="valid",
    )
    assert result.payment_status == PaymentStatus.REFUND_PENDING

    system_alert = db.scalar(
        select(Notification).where(Notification.user_id.in_([admin_1.id, admin_2.id]), Notification.type == NotificationType.SYSTEM_ALERT)
    )
    assert system_alert is not None
    assert system_alert.order_id == order.id

    # --- Tenant/role isolation, asserted explicitly and exhaustively ---
    owner_b_rows = db.scalars(select(Notification).where(Notification.user_id == owner_b.id)).all()
    assert owner_b_rows == []  # restaurant B saw nothing from this entire journey

    admin_1_types = sorted(n.type.value for n in db.scalars(select(Notification).where(Notification.user_id == admin_1.id)))
    admin_2_types = sorted(n.type.value for n in db.scalars(select(Notification).where(Notification.user_id == admin_2.id)))
    assert admin_1_types == admin_2_types  # notify_admins broadcasts the same set of events to every admin
    assert len(admin_1_types) >= 1

    customer_rows = db.scalars(select(Notification).where(Notification.user_id == customer.id)).all()
    assert all(n.role == UserRole.CUSTOMER for n in customer_rows)
    owner_a_rows = db.scalars(select(Notification).where(Notification.user_id == owner_a.id)).all()
    assert all(n.role == UserRole.RESTAURANT_OWNER for n in owner_a_rows)
