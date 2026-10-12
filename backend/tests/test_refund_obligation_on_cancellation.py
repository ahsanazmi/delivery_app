"""E2E Validation Phase 26 — a paid online order that gets cancelled or
rejected must record a refund obligation (REFUND_PENDING), and that state
must actually be refundable. Reproduced live: the payment stayed PAID after
customer cancel / restaurant reject / admin cancel, and REFUND_PENDING (also
used by the webhook for late captures on dead orders) wasn't refundable."""

from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.user import User, UserRole
from app.services.orders import cancel_order, reject_order, transition_order_status
from app.services.payment.provider import ProviderRefund
from app.services.payment.refund_service import create_refund
from tests.test_restaurant_portal_final_suite import _owner, _place_order, _restaurant


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, autoflush=False) as session:
        yield session
    Base.metadata.drop_all(engine)


def _paid_online_order(db, suffix):
    restaurant = _restaurant(db, _owner(db, email=f"owner{suffix}@example.com", phone=f"90000000{suffix}"), name=f"R{suffix}")
    order = _place_order(db, restaurant, Decimal("100.00"), suffix=suffix)
    order.payment_method = "razorpay"
    order.is_paid = True
    order.payment_status = "paid"
    db.add(Payment(order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY, amount=order.total,
                   payment_status=PaymentStatus.PAID, razorpay_order_id=f"order_{suffix}", razorpay_payment_id=f"pay_{suffix}"))
    db.add(User(name="Admin", email=f"admin{suffix}@example.com", password_hash="x", role=UserRole.ADMIN))
    db.commit()
    return restaurant, order


def _payment(db, order):
    return db.query(Payment).filter(Payment.order_id == order.id).one()


def test_customer_cancelling_a_paid_online_order_records_a_refund_obligation(db):
    _, order = _paid_online_order(db, "1")
    cancel_order(db, order.user_id, order.id, "changed my mind")
    assert _payment(db, order).payment_status == PaymentStatus.REFUND_PENDING
    assert db.get(type(order), order.id).payment_status == "refund_pending"
    assert db.query(Notification).filter(Notification.type == NotificationType.SYSTEM_ALERT, Notification.order_id == order.id).count() == 1


def test_restaurant_rejecting_a_paid_online_order_records_a_refund_obligation(db):
    restaurant, order = _paid_online_order(db, "2")
    reject_order(db, restaurant.id, order.id, "out of stock")
    assert _payment(db, order).payment_status == PaymentStatus.REFUND_PENDING


def test_an_unpaid_or_cod_cancellation_records_nothing(db):
    restaurant = _restaurant(db, _owner(db, email="owner3@example.com", phone="9000000003"), name="R3")
    order = _place_order(db, restaurant, Decimal("100.00"), suffix="3")
    transition_order_status(db, order, OrderStatus.CANCELLED, "test")
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 0


class _Provider:
    def initiate_refund(self, **kwargs):
        return ProviderRefund(provider_refund_id="rfnd_test", status="processed", amount=kwargs["amount"])


def test_a_refund_pending_payment_can_actually_be_refunded(db):
    _, order = _paid_online_order(db, "4")
    cancel_order(db, order.user_id, order.id, "changed my mind")
    payment = _payment(db, order)
    assert payment.payment_status == PaymentStatus.REFUND_PENDING

    create_refund(db, payment=payment, amount=payment.amount, reason="Order cancelled", provider=_Provider())
    db.commit()
    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.REFUNDED
