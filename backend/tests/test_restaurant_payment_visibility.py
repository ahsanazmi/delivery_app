"""Restaurant Owner Portal — Phase 28: Restaurant Payment Visibility.

Covers: the restaurant owner can see order amount, restaurant earning,
commission, net amount, payment method, and payment status for their own
orders (list and detail), the figures never move once an order is placed
even if the platform's commission rule changes afterward, and nothing
payment-secret-related is ever exposed.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.commission_rule import CommissionRule, CommissionType
from app.models.order import Order
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import compute_restaurant_financials, create_order

RESTAURANT_ORDERS_URL = "/api/v1/restaurant/orders"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _owner(db, email="owner-p28@example.com", phone="9000000028"):
    user = User(name="Owner", email=email, phone=phone, password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db, owner):
    restaurant = Restaurant(
        owner_id=owner.id, name="Diner P28", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, restaurant, *, price=Decimal("100.00"), suffix="1"):
    customer = User(name="Cust", email=f"cust-p28-{suffix}@example.com", phone=f"93{suffix.zfill(8)}", password_hash="x", role=UserRole.CUSTOMER)
    db.add(customer)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=price)
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Cust", "phone": "9999999999",
        "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def _client(engine):
    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


# ---------------------------------------------------------------------------
# compute_restaurant_financials — pure function
# ---------------------------------------------------------------------------


def test_financials_treat_a_never_configured_commission_as_zero(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)
    assert order.commission_amount is None  # no CommissionRule exists at all in this test DB

    financials = compute_restaurant_financials(order)
    assert financials["commission"] == Decimal("0.00")
    assert financials["restaurant_earning"] == order.subtotal
    assert financials["net_amount"] == order.subtotal


def test_financials_derive_net_amount_from_the_orders_own_snapshot(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    db.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00")))
    db.commit()
    order = _place_order(db, restaurant, price=Decimal("200.00"))

    assert order.commission_amount == Decimal("20.00")  # 10% of 200 subtotal
    financials = compute_restaurant_financials(order)
    assert financials["commission"] == Decimal("20.00")
    assert financials["restaurant_earning"] == Decimal("200.00")
    assert financials["net_amount"] == Decimal("180.00")


def test_a_commission_rate_change_never_retroactively_changes_a_placed_orders_figures(db):
    """The phase's own explicit requirement: 'Historical financial values
    must remain stable.' An order's commission/earning/net figures are
    frozen at the moment it's placed — changing (or even deleting) the
    CommissionRule afterward must never alter what an already-placed
    order reports."""
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    rule = CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00"))
    db.add(rule)
    db.commit()
    order = _place_order(db, restaurant, price=Decimal("200.00"))

    before = compute_restaurant_financials(order)
    assert before["commission"] == Decimal("20.00")

    # The admin changes the platform default commission rate after the
    # order was already placed.
    rule.value = Decimal("50.00")
    db.commit()

    after = compute_restaurant_financials(order)
    assert after == before  # completely unchanged despite the new rate


# ---------------------------------------------------------------------------
# GET /restaurant/orders — list
# ---------------------------------------------------------------------------


def test_list_includes_all_six_required_fields(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    db.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00")))
    db.commit()
    order = _place_order(db, restaurant, price=Decimal("100.00"))
    engine = db.get_bind()

    with _client(engine) as client:
        token = create_access_token(owner.id)
        response = client.get(RESTAURANT_ORDERS_URL, headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    item = next(i for i in response.json() if i["id"] == str(order.id))
    assert Decimal(item["total"]) == order.total  # Order amount
    assert Decimal(item["restaurant_earning"]) == Decimal("100.00")
    assert Decimal(item["commission"]) == Decimal("10.00")
    assert Decimal(item["net_amount"]) == Decimal("90.00")
    assert item["payment_method"] == "cod"
    assert item["payment_status"] == "pending"


def test_list_never_exposes_any_payment_secret_or_provider_id(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    order = _place_order(db, restaurant)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PAID, amount=order.total,
        razorpay_order_id="order_p28_secret", razorpay_payment_id="pay_p28_secret",
        razorpay_signature="super-secret-signature-p28",
    )
    db.add(payment)
    db.commit()
    engine = db.get_bind()

    with _client(engine) as client:
        token = create_access_token(owner.id)
        response = client.get(RESTAURANT_ORDERS_URL, headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()

    raw_text = response.text
    assert "super-secret-signature-p28" not in raw_text
    assert "razorpay_signature" not in raw_text
    assert "razorpay_order_id" not in raw_text
    assert "razorpay_payment_id" not in raw_text
    assert "order_p28_secret" not in raw_text
    assert "pay_p28_secret" not in raw_text


# ---------------------------------------------------------------------------
# GET /restaurant/orders/{id} — detail, and the action endpoints that
# return the same shape
# ---------------------------------------------------------------------------


def test_detail_includes_all_six_required_fields_and_never_leaks_secrets(db):
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    db.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.FIXED, value=Decimal("15.00")))
    db.commit()
    order = _place_order(db, restaurant, price=Decimal("100.00"))
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PAID, amount=order.total,
        razorpay_signature="super-secret-signature-p28-detail",
    )
    db.add(payment)
    db.commit()
    engine = db.get_bind()

    with _client(engine) as client:
        token = create_access_token(owner.id)
        response = client.get(f"{RESTAURANT_ORDERS_URL}/{order.id}", headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["total"]) == order.total
    assert Decimal(body["restaurant_earning"]) == Decimal("100.00")
    assert Decimal(body["commission"]) == Decimal("15.00")
    assert Decimal(body["net_amount"]) == Decimal("85.00")
    assert body["payment_method"] == "cod"
    assert body["payment_status"] == "pending"
    assert "super-secret-signature-p28-detail" not in response.text
    assert "razorpay_signature" not in response.text


def test_owner_cannot_see_another_restaurants_order_financials(db):
    owner_a = _owner(db, email="owner-p28-a@example.com", phone="9000000029")
    restaurant_a = _restaurant(db, owner_a)
    order_a = _place_order(db, restaurant_a, suffix="a")

    owner_b = _owner(db, email="owner-p28-b@example.com", phone="9000000030")
    _restaurant(db, owner_b)
    engine = db.get_bind()

    with _client(engine) as client:
        token_b = create_access_token(owner_b.id)
        response = client.get(f"{RESTAURANT_ORDERS_URL}/{order_a.id}", headers={"Authorization": f"Bearer {token_b}"})
    app.dependency_overrides.clear()

    assert response.status_code == 404


def test_accepting_an_online_paid_order_still_returns_the_financial_fields(db):
    """The accept/reject/preparing/ready action endpoints all hand back
    the freshly-updated order — they must keep returning the same
    restaurant-financial fields the initial GET does, or the owner's UI
    would lose them the moment it takes any action."""
    owner = _owner(db)
    restaurant = _restaurant(db, owner)
    db.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00")))
    db.commit()
    order = _place_order(db, restaurant, price=Decimal("100.00"))
    # accept_order() requires an online order to already be paid.
    order.payment_method = "razorpay"
    order.is_paid = True
    db.commit()
    engine = db.get_bind()

    with _client(engine) as client:
        token = create_access_token(owner.id)
        response = client.post(f"{RESTAURANT_ORDERS_URL}/{order.id}/accept", headers={"Authorization": f"Bearer {token}"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["restaurant_earning"]) == Decimal("100.00")
    assert Decimal(body["commission"]) == Decimal("10.00")
    assert Decimal(body["net_amount"]) == Decimal("90.00")
