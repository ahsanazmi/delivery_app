from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status
from app.services.payments import record_order_payment, verify_payment


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
        delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _rider(db):
    rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
    db.add(rider)
    db.commit()
    return rider


def _place_order(db, customer, restaurant):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
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
    return create_order(db, customer, address.id)


def _advance_to_out_for_delivery(db, order, rider):
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    assign_rider_to_order(db, order, rider.id)
    transition_order_status(db, order, OrderStatus.PICKED_UP)
    transition_order_status(db, order, OrderStatus.OUT_FOR_DELIVERY)
    db.commit()


def test_order_starts_as_cod_pending(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    assert order.payment_method == "cod"
    assert order.payment_status == "pending"
    assert order.is_paid is False


def test_delivery_marks_cod_payment_paid(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = _rider(db)
    order = _place_order(db, customer, restaurant)
    record_order_payment(db, customer.id, order.id)

    _advance_to_out_for_delivery(db, order, rider)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()

    assert order.payment_status == "paid"
    assert order.is_paid is True
    payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    assert payment.payment_status == PaymentStatus.PAID


def test_delivery_without_a_payment_record_still_settles_order_fields(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = _rider(db)
    order = _place_order(db, customer, restaurant)
    # No record_order_payment call this time — Phase 14's payment row is optional.

    _advance_to_out_for_delivery(db, order, rider)
    transition_order_status(db, order, OrderStatus.DELIVERED)
    db.commit()

    assert order.payment_status == "paid"
    assert order.is_paid is True


def test_customer_cannot_mark_cod_payment_paid_via_online_verification(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)
    result = record_order_payment(db, customer.id, order.id)
    payment = db.get(Payment, result["payment_id"])
    assert payment.provider == PaymentProvider.COD

    with pytest.raises(HTTPException) as exc_info:
        verify_payment(
            db,
            payment=payment,
            payload={"razorpay_order_id": "fake", "razorpay_payment_id": "fake", "signature": "fake"},
        )
    assert exc_info.value.status_code == 400
    assert payment.payment_status == PaymentStatus.PENDING


def test_payment_stays_pending_before_delivery(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    rider = _rider(db)
    order = _place_order(db, customer, restaurant)
    record_order_payment(db, customer.id, order.id)

    _advance_to_out_for_delivery(db, order, rider)
    assert order.payment_status == "pending"
    assert order.is_paid is False
