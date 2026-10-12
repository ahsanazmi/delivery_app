"""E2E Validation Phase 9 — transition_order_status() refreshed the order
from the database after its status UPDATE, which silently discarded any
field the caller had set just before (rider_id, cancelled_reason) because
the app's sessions don't autoflush. Reproduced on PostgreSQL: an admin
assignment left the order RIDER_ASSIGNED with rider_id NULL, and
rejection/cancellation reasons were lost. These tests use a non-autoflush
session, exactly like app.db.session.SessionLocal."""

from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.order import Order, OrderStatus
from app.services.orders import cancel_order, reject_order
from tests.test_restaurant_portal_final_suite import _owner, _place_order, _restaurant


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return engine


def test_a_restaurant_rejection_reason_is_persisted():
    engine = _engine()
    with Session(engine, autoflush=False) as db:
        restaurant = _restaurant(db, _owner(db))
        order = _place_order(db, restaurant, Decimal("100.00"))
        reject_order(db, restaurant.id, order.id, "Out of stock")
        order_id = order.id

    with Session(engine) as fresh:
        stored = fresh.get(Order, order_id)
        assert stored.status == OrderStatus.REJECTED
        assert stored.cancelled_reason == "Out of stock"


def test_a_customer_cancellation_reason_is_persisted():
    engine = _engine()
    with Session(engine, autoflush=False) as db:
        restaurant = _restaurant(db, _owner(db))
        order = _place_order(db, restaurant, Decimal("100.00"))
        cancel_order(db, order.user_id, order.id, "Ordered by mistake")
        order_id = order.id

    with Session(engine) as fresh:
        stored = fresh.get(Order, order_id)
        assert stored.status == OrderStatus.CANCELLED
        assert stored.cancelled_reason == "Ordered by mistake"
