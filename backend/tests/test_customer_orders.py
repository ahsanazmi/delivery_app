from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import Order, OrderStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import cancel_order, create_order, transition_order_status


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com", phone="9999999999"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER, phone=phone)
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


def _ordered_setup(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
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
    return customer, restaurant, address


def test_valid_transitions_allowed():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        customer, _, address = _ordered_setup(db)
        order = create_order(db, customer, address.id)
        assert order.status == OrderStatus.PLACED

        transition_order_status(db, order, OrderStatus.CONFIRMED)
        db.commit()
        assert order.status == OrderStatus.CONFIRMED
        assert len(order.status_history) == 2
    Base.metadata.drop_all(engine)


def test_two_concurrent_place_order_calls_never_create_two_orders(db, monkeypatch):
    """Integration Phase 16 — reproduces the exact race create_order is
    exposed to: two requests both run validate_checkout (read-mostly, safe
    concurrently) before either has claimed the cart via the atomic
    conditional UPDATE. Simulates a competitor winning that claim in the
    gap between this call's own validate_checkout read and its claim
    attempt — the loser must raise a clean "cart is empty" error and must
    not create a second Order, exactly as confirmed live against real
    Postgres with two genuinely simultaneous HTTP requests (see this
    phase's completion report)."""
    from sqlalchemy import update

    from app.models.cart import Cart
    from app.services import orders as orders_module

    customer, _, address = _ordered_setup(db)
    real_validate_checkout = orders_module.validate_checkout

    def validate_checkout_then_let_a_competitor_win(db_, user, address_id):
        result = real_validate_checkout(db_, user, address_id)
        # A concurrent second call wins the atomic claim first, in the gap
        # between this read and our own claim attempt below.
        db_.execute(update(Cart).where(Cart.id == result["cart"].id).values(restaurant_id=None))
        db_.commit()
        return result

    monkeypatch.setattr(orders_module, "validate_checkout", validate_checkout_then_let_a_competitor_win)

    with pytest.raises(ValueError, match="cart is empty"):
        create_order(db, customer, address.id)

    assert db.query(Order).filter(Order.user_id == customer.id).count() == 0


def test_a_mid_order_creation_failure_does_not_leave_the_cart_permanently_claimed(db, monkeypatch):
    """Database Transaction Testing (Phase 24) — create_order's cart claim
    (the atomic conditional UPDATE from Phase 16) must live or die with the
    rest of order creation, not commit on its own. Simulates a failure
    (commission computation raising) that happens *after* the claim
    succeeds but *before* the final commit: the whole operation must roll
    back together, leaving the cart exactly as it was (still claimed by
    this customer, items intact) so a normal retry succeeds — not a
    permanently "empty" cart the customer can never order from again."""
    from app.services import orders as orders_module

    customer, _, address = _ordered_setup(db)

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated failure after the cart claim")

    monkeypatch.setattr(orders_module, "compute_effective_commission", boom)

    with pytest.raises(RuntimeError, match="simulated failure"):
        create_order(db, customer, address.id)

    assert db.query(Order).filter(Order.user_id == customer.id).count() == 0

    db.expire_all()
    cart = orders_module.get_cart_for_user(db, customer.id)
    assert cart.restaurant_id is not None
    assert len(cart.items) == 1

    monkeypatch.undo()
    order = create_order(db, customer, address.id)
    assert order.status == OrderStatus.PLACED
    assert db.query(Order).filter(Order.user_id == customer.id).count() == 1


def test_listing_orders_does_not_issue_a_query_per_order_for_items_and_history(db):
    """Performance Baseline (Phase 25) — OrderRead (this endpoint's response
    schema) serializes every order's .items and .status_history. Without
    eager loading, each one of those relationships is a separate lazy-load
    query per order in the page — a genuine N+1 that would scale with page
    size. Verified directly the same way Phase 30's rider-performance suite
    already proves its own N+1 fixes: listing several orders, each with
    several items and status-history entries, must issue a small, fixed
    number of queries — not one extra pair per order."""
    from sqlalchemy import event

    from app.services.orders import list_user_orders, transition_order_status

    customer, restaurant, address = _ordered_setup(db)
    product1 = db.query(Product).filter(Product.restaurant_id == restaurant.id).one()
    product2 = Product(restaurant_id=restaurant.id, name="Extra Item", price=Decimal("50.00"))
    db.add(product2)
    db.commit()

    for _ in range(5):
        cart = create_cart_for_user(db, customer.id)
        add_item(db, cart, product1.id, 1)
        add_item(db, cart, product2.id, 1)
        order = create_order(db, customer, address.id)
        transition_order_status(db, order, OrderStatus.CONFIRMED)

    # create_order's own commits expire every object in the session (the
    # SQLAlchemy default) — touch customer.id now so that expiry-driven
    # reload happens before the listener starts, and isn't mistaken for a
    # query list_user_orders itself issued.
    customer_id = customer.id

    queries = []
    engine = db.get_bind()
    listener = lambda *args: queries.append(args)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listener)
    try:
        results = list_user_orders(db, customer_id)
        assert len(results) == 5
        for order in results:
            assert len(order.items) == 2
            assert len(order.status_history) == 2
    finally:
        event.remove(engine, "before_cursor_execute", listener)

    # One query for the orders themselves, one batched query for .items,
    # one batched query for .status_history — fixed, regardless of how many
    # orders or how many items/history entries each one has.
    assert len(queries) <= 3, f"Expected a small fixed query count, got {len(queries)}"


def test_invalid_transition_rejected(db):
    customer, _, address = _ordered_setup(db)
    order = create_order(db, customer, address.id)

    with pytest.raises(ValueError, match="Cannot move"):
        transition_order_status(db, order, OrderStatus.DELIVERED)


def test_customer_can_cancel_while_placed(db):
    customer, _, address = _ordered_setup(db)
    order = create_order(db, customer, address.id)

    cancelled = cancel_order(db, customer.id, order.id, "Changed my mind")
    assert cancelled.status == OrderStatus.CANCELLED
    assert cancelled.cancelled_reason == "Changed my mind"


def test_customer_cannot_cancel_once_preparing(db):
    customer, _, address = _ordered_setup(db)
    order = create_order(db, customer, address.id)
    transition_order_status(db, order, OrderStatus.CONFIRMED)
    transition_order_status(db, order, OrderStatus.PREPARING)
    db.commit()

    with pytest.raises(HTTPException) as exc_info:
        cancel_order(db, customer.id, order.id)
    assert exc_info.value.status_code == 409


def test_order_snapshot_survives_product_and_restaurant_changes(db):
    customer, restaurant, address = _ordered_setup(db)
    order = create_order(db, customer, address.id)
    order_id = order.id
    item_name = order.items[0].product_name
    item_price = order.items[0].unit_price

    # Mutate the live restaurant/product data after the order was placed.
    restaurant.name = "Renamed Restaurant"
    db.query(Order).filter(Order.id == order_id)  # no-op, just touching session
    db.commit()

    reloaded = db.get(Order, order_id)
    assert reloaded.restaurant_name == "Chai House"  # snapshot, not live name
    assert reloaded.items[0].product_name == item_name
    assert reloaded.items[0].unit_price == item_price


def test_customer_cannot_order_from_someone_elses_address(db):
    customer, restaurant, _ = _ordered_setup(db)
    other = _customer(db, email="other@example.com", phone="8887776666")
    other_address = create_address(db, other.id, {
        "label": "Home",
        "recipient_name": "Other",
        "phone": "8888888888",
        "address_line": "1 Other Street",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560002",
    })

    with pytest.raises(ValueError, match="valid delivery address"):
        create_order(db, customer, other_address.id)


def test_customer_order_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer, restaurant, address = _ordered_setup(seed)
            from app.core.security import create_access_token

            token = create_access_token(customer.id)
            address_id = address.id

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            create = client.post(
                "/api/v1/customer/orders", headers=headers, json={"address_id": str(address_id)}
            )
            assert create.status_code == 201
            order_id = create.json()["id"]
            assert create.json()["status"] == "placed"
            assert create.json()["customer_name"] == "Customer"

            listing = client.get("/api/v1/customer/orders", headers=headers)
            assert listing.status_code == 200
            assert len(listing.json()) == 1

            detail = client.get(f"/api/v1/customer/orders/{order_id}", headers=headers)
            assert detail.status_code == 200

            cancel = client.post(f"/api/v1/customer/orders/{order_id}/cancel", headers=headers)
            assert cancel.status_code == 200
            assert cancel.json()["status"] == "cancelled"

            second_cancel = client.post(f"/api/v1/customer/orders/{order_id}/cancel", headers=headers)
            assert second_cancel.status_code == 409
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
