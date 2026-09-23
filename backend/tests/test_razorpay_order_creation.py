"""Payment System Phase 12 — RAZORPAY ORDER CREATION.

Covers: the full checkout -> validate -> create Razorpay order -> store
provider order id -> return checkout information flow, proving the amount
sent to Razorpay is always the backend's own authoritative order.total,
never anything the client could supply, and that the returned checkout
information includes what the mobile app's Razorpay Checkout SDK actually
needs (the public key_id) without ever leaking the secret.
"""
from decimal import Decimal

import httpx
import pytest

from app.core.config import settings
from app.db.base import Base
from app.models.payment import Payment, PaymentProvider
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order
from app.services.payments import record_order_payment
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _order(db, customer, restaurant, price=Decimal("175.00")):
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id, payment_method="razorpay")


def _mock_transport(expected_amount_paise):
    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        assert body["amount"] == expected_amount_paise, "Razorpay order amount must match the server total exactly"
        return httpx.Response(200, json={
            "id": "order_phase12fake", "amount": body["amount"], "currency": "INR", "status": "created",
        })
    return httpx.MockTransport(handler)


def test_razorpay_order_amount_is_always_the_servers_authoritative_total(db, monkeypatch):
    """order.total — the server-computed subtotal plus the restaurant's own
    delivery fee, set once at order-creation time (create_order()) — is what
    must reach Razorpay, in paise, never anything else, regardless of what a
    client might have tried to claim during checkout (CustomerOrderCreate
    accepts no amount field at all, so there is nothing to spoof upstream of
    this either)."""
    from app.services.payment.razorpay_provider import RazorpayProvider

    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _order(db, customer, restaurant, price=Decimal("175.00"))
    expected_paise = int(order.total * 100)

    def fake_provider(*args, **kwargs):
        return RazorpayProvider(key_id="rzp_test_fake_key", key_secret="fake_secret", transport=_mock_transport(expected_paise))

    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", fake_provider)

    result = record_order_payment(db, customer.id, order.id)
    assert result["amount"] == order.total
    assert result["transaction_reference"] == "order_phase12fake"


def test_provider_order_id_is_stored_on_the_payment_row(db, monkeypatch):
    from app.services.payment.razorpay_provider import RazorpayProvider

    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _order(db, customer, restaurant)
    expected_paise = int(order.total * 100)

    def fake_provider(*args, **kwargs):
        return RazorpayProvider(key_id="rzp_test_fake_key", key_secret="fake_secret", transport=_mock_transport(expected_paise))

    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", fake_provider)

    record_order_payment(db, customer.id, order.id)
    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment.provider == PaymentProvider.RAZORPAY
    assert payment.razorpay_order_id == "order_phase12fake"


def test_checkout_information_includes_the_public_key_id_but_never_the_secret(db, monkeypatch):
    from app.services.payment.razorpay_provider import RazorpayProvider

    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret_must_never_leak")

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _order(db, customer, restaurant)
    expected_paise = int(order.total * 100)

    def fake_provider(*args, **kwargs):
        return RazorpayProvider(key_id="rzp_test_fake_key", key_secret="fake_secret_must_never_leak", transport=_mock_transport(expected_paise))

    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", fake_provider)

    result = record_order_payment(db, customer.id, order.id)
    assert result["razorpay_key_id"] == "rzp_test_fake_key"
    assert "fake_secret_must_never_leak" not in str(result)


def test_cod_checkout_information_has_no_razorpay_key(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    order = create_order(db, customer, address.id, payment_method="cod")

    result = record_order_payment(db, customer.id, order.id)
    assert result["razorpay_key_id"] is None
