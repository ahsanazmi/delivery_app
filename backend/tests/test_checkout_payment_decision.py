"""Payment System Phase 6 — CHECKOUT PAYMENT DECISION.

Covers: the schema only accepts the two real methods, create_order()
refuses "razorpay" when online payment isn't actually configured,
record_order_payment() creates a genuine online Payment (with a real
provider_order_id) via PaymentService when it is configured, COD keeps
working unchanged, and the server always recalculates subtotal/delivery
fee/tax/discount/total itself regardless of any client-supplied values.
"""
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.db.base import Base
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.user import User, UserRole
from app.models.restaurant import Restaurant
from app.models.product import Product
from app.schemas.order import CustomerOrderCreate
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
        owner_id=owner.id,
        name="Chai House",
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _cart_and_address(db, customer, restaurant, price=Decimal("100.00")):
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })
    return address


# ---- schema ----

def test_schema_accepts_cod_and_razorpay():
    assert CustomerOrderCreate(address_id="00000000-0000-0000-0000-000000000001", payment_method="cod")
    assert CustomerOrderCreate(address_id="00000000-0000-0000-0000-000000000001", payment_method="razorpay")


def test_schema_rejects_any_other_payment_method():
    with pytest.raises(ValidationError):
        CustomerOrderCreate(address_id="00000000-0000-0000-0000-000000000001", payment_method="cash")


def test_schema_defaults_to_cod():
    payload = CustomerOrderCreate(address_id="00000000-0000-0000-0000-000000000001")
    assert payload.payment_method == "cod"


# ---- create_order() availability gate ----

def test_create_order_rejects_razorpay_when_not_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "")
    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant)

    with pytest.raises(ValueError, match="Online payment is not currently available"):
        create_order(db, customer, address.id, payment_method="razorpay")


def test_create_order_accepts_razorpay_when_configured(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")
    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant)

    order = create_order(db, customer, address.id, payment_method="razorpay")
    assert order.payment_method == "razorpay"


def test_create_order_cod_unaffected_by_razorpay_configuration_state(db, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "")
    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant)

    order = create_order(db, customer, address.id, payment_method="cod")
    assert order.payment_method == "cod"


# ---- server-authoritative amounts ----

def test_order_totals_are_always_server_computed_never_client_supplied(db):
    """CustomerOrderCreate carries no client_total/discount/tax/delivery_fee
    fields at all — there is nothing for create_order() to trust, because
    the schema never accepts them in the first place. This proves the
    resulting order's amounts trace back only to the catalog/restaurant
    data actually in the database."""
    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant, price=Decimal("100.00"))

    assert not hasattr(CustomerOrderCreate.model_fields, "client_total")
    for forbidden in ("client_total", "client_discount", "client_tax", "client_delivery_fee"):
        assert forbidden not in CustomerOrderCreate.model_fields

    order = create_order(db, customer, address.id)
    assert order.subtotal == Decimal("100.00")
    assert order.delivery_fee == restaurant.delivery_fee
    assert order.total == order.subtotal + order.delivery_fee + order.tax - order.discount


# ---- record_order_payment() delegating to PaymentService for razorpay ----

def _mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/orders"
        return httpx.Response(200, json={
            "id": "order_phase6fake123", "amount": 10000, "currency": "INR", "status": "created",
        })
    return httpx.MockTransport(handler)


def test_record_order_payment_creates_real_online_payment_when_configured(db, monkeypatch):
    from app.services.payment.razorpay_provider import RazorpayProvider

    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake_secret")

    def fake_provider(*args, **kwargs):
        return RazorpayProvider(key_id="rzp_test_fake", key_secret="fake_secret", transport=_mock_transport())

    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", fake_provider)

    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant, price=Decimal("100.00"))
    order = create_order(db, customer, address.id, payment_method="razorpay")

    result = record_order_payment(db, customer.id, order.id)
    assert result["method"] == "online"
    assert result["status"] == PaymentStatus.PENDING
    assert result["transaction_reference"] == "order_phase6fake123"

    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment.provider == PaymentProvider.RAZORPAY
    assert payment.razorpay_order_id == "order_phase6fake123"


def test_record_order_payment_cod_flow_still_works_unchanged(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    address = _cart_and_address(db, customer, restaurant)
    order = create_order(db, customer, address.id, payment_method="cod")

    result = record_order_payment(db, customer.id, order.id)
    assert result["method"] == "cod"
    assert result["status"] == PaymentStatus.PENDING
    assert result["transaction_reference"] is None
