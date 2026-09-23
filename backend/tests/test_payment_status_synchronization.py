"""Payment System Phase 16 — PAYMENT STATUS SYNCHRONIZATION.

Covers: a successful verify_payment() syncs Order.payment_status/is_paid
and nothing else (never order.status, never anything restaurant- or
rider-side); and the documented business rule this phase asked for a
decision on — an online (razorpay) order stays invisible/unacceptable to
the restaurant until its payment is confirmed, while COD is completely
unaffected.
"""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.db.base import Base
from app.models.order import OrderStatus
from app.models.payment import PaymentStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import accept_order, create_order, list_restaurant_orders
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.restaurant_dashboard import get_restaurant_dashboard


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


class GenuineFakeProvider(PaymentProvider):
    name = "genuine-fake"

    def create_order(self, *, amount, currency, receipt, notes=None):
        return ProviderOrder(provider_order_id=f"order_p16_{receipt}", amount=amount, currency=currency, status="created")

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return True

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=self._order_id,
            status="captured", amount=self._amount, currency="INR",
        )

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=self._amount, currency="INR", status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_p16", status="processed", amount=amount)

    def verify_webhook_signature(self, *, payload, signature):
        return True

    def set_expectations(self, *, order_id: str, amount: Decimal):
        self._order_id = order_id
        self._amount = amount


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, tag="p16"):
    owner = User(name="Owner", email=f"owner-{tag}@example.com", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _order(db, customer, restaurant, payment_method="razorpay", price=Decimal("200.00")):
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id, payment_method=payment_method)


def test_successful_verification_syncs_order_payment_fields_only(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    fake = GenuineFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    customer = _customer(db)
    restaurant = _restaurant(db, "sync")
    order = _order(db, customer, restaurant)
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    fake.set_expectations(order_id=payment.razorpay_order_id, amount=payment.amount)

    before_status = order.status
    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p16_1", signature="whatever-the-fake-accepts",
    )

    db.refresh(order)
    assert order.payment_status == "paid"
    assert order.is_paid is True
    # Nothing else moved — order.status stays exactly where create_order() left it.
    assert order.status == before_status == OrderStatus.PLACED
    assert order.rider_id is None
    db.refresh(restaurant)
    assert restaurant.is_active is True  # untouched


def test_unpaid_online_order_is_hidden_from_the_restaurants_order_list(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    customer = _customer(db)
    restaurant = _restaurant(db, "hide")
    order = _order(db, customer, restaurant, payment_method="razorpay")

    orders = list_restaurant_orders(db, restaurant.id)
    assert order.id not in {o.id for o in orders}

    pending = list_restaurant_orders(db, restaurant.id, status_filter="pending")
    assert order.id not in {o.id for o in pending}


def test_unpaid_online_order_is_excluded_from_the_dashboards_pending_count(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    customer = _customer(db)
    restaurant = _restaurant(db, "dash")
    _order(db, customer, restaurant, payment_method="razorpay")

    dashboard = get_restaurant_dashboard(db, restaurant)
    assert dashboard["pending_orders_count"] == 0
    assert dashboard["pending_orders"] == []


def test_restaurant_cannot_accept_an_unpaid_online_order_even_by_direct_id(db, monkeypatch):
    """The list-visibility hiding is a UX convenience, not the real
    guard — this proves the actual state-mutating action is blocked
    regardless of how the restaurant obtained the order id."""
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    customer = _customer(db)
    restaurant = _restaurant(db, "block")
    order = _order(db, customer, restaurant, payment_method="razorpay")

    with pytest.raises(Exception) as exc_info:
        accept_order(db, restaurant.id, order.id)
    assert getattr(exc_info.value, "status_code", None) == 409

    db.refresh(order)
    assert order.status == OrderStatus.PLACED  # never moved to CONFIRMED


def test_once_paid_the_order_becomes_visible_and_acceptable(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    fake = GenuineFakeProvider()
    service = PaymentService(providers={"razorpay": fake})
    customer = _customer(db)
    restaurant = _restaurant(db, "unlock")
    order = _order(db, customer, restaurant)
    payment = service.create_payment_for_order(db, order=order, method="razorpay")
    fake.set_expectations(order_id=payment.razorpay_order_id, amount=payment.amount)
    service.verify_payment(
        db, payment=payment, provider_order_id=payment.razorpay_order_id,
        provider_payment_id="pay_p16_2", signature="ok",
    )
    db.refresh(order)

    orders = list_restaurant_orders(db, restaurant.id, status_filter="pending")
    assert order.id in {o.id for o in orders}

    accepted = accept_order(db, restaurant.id, order.id)
    assert accepted.status == OrderStatus.CONFIRMED


def test_cod_orders_are_completely_unaffected_by_the_online_payment_gate(db):
    customer = _customer(db)
    restaurant = _restaurant(db, "cod")
    order = _order(db, customer, restaurant, payment_method="cod")

    # A COD order is visible and acceptable immediately, is_paid=False notwithstanding.
    orders = list_restaurant_orders(db, restaurant.id, status_filter="pending")
    assert order.id in {o.id for o in orders}

    accepted = accept_order(db, restaurant.id, order.id)
    assert accepted.status == OrderStatus.CONFIRMED
