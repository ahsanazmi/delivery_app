"""Admin Portal — Phase 17: Commission Management.

Two halves: admin CRUD over the commission configuration (using the shared
`client` fixture), and a real end-to-end proof that changing a commission
rule never alters an order's already-snapshotted commission (using a
dedicated engine + real HTTP order placement).
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Order, Product, Restaurant, User, UserRole
from app.services.addresses import create_address

COMMISSIONS_URL = "/api/v1/admin/commissions"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p17@example.com", phone="8000000001", role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_restaurant(db, suffix):
    owner = _make_user(db, name=f"Owner {suffix}", email=f"owner-{suffix}-p17@example.com", phone=f"800000001{suffix}", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Restaurant {suffix}", phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_get_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p17@example.com", phone="8000000010", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(COMMISSIONS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(COMMISSIONS_URL).status_code == 401


def test_get_when_nothing_configured_returns_null_default(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.get(COMMISSIONS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["default"] is None
    assert body["restaurant_overrides"] == []


def test_set_percentage_default(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(COMMISSIONS_URL, headers=headers, json={"default": {"commission_type": "PERCENTAGE", "value": "10.00"}})
    assert response.status_code == 200
    body = response.json()
    assert body["default"]["commission_type"] == "PERCENTAGE"
    assert Decimal(body["default"]["value"]) == Decimal("10.00")


def test_updating_default_twice_updates_the_same_rule_not_a_second_one(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.patch(COMMISSIONS_URL, headers=headers, json={"default": {"commission_type": "PERCENTAGE", "value": "10.00"}})
    client.patch(COMMISSIONS_URL, headers=headers, json={"default": {"commission_type": "FIXED", "value": "25.00"}})

    response = client.get(COMMISSIONS_URL, headers=headers)
    body = response.json()
    assert body["default"]["commission_type"] == "FIXED"
    assert Decimal(body["default"]["value"]) == Decimal("25.00")


def test_percentage_default_cannot_exceed_100(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(COMMISSIONS_URL, headers=headers, json={"default": {"commission_type": "PERCENTAGE", "value": "150.00"}})
    assert response.status_code == 422


def test_value_must_be_positive(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(COMMISSIONS_URL, headers=headers, json={"default": {"commission_type": "PERCENTAGE", "value": "0"}})
    assert response.status_code == 422


def test_upsert_restaurant_override(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "1")

    response = client.patch(
        COMMISSIONS_URL, headers=headers,
        json={"upsert_restaurant_overrides": [{"restaurant_id": str(restaurant.id), "commission_type": "FIXED", "value": "15.00"}]},
    )
    assert response.status_code == 200
    body = response.json()
    override = next(o for o in body["restaurant_overrides"] if o["restaurant_id"] == str(restaurant.id))
    assert override["commission_type"] == "FIXED"
    assert Decimal(override["value"]) == Decimal("15.00")
    assert override["restaurant_name"] == "Restaurant 1"


def test_upsert_override_for_nonexistent_restaurant_404s(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(
        COMMISSIONS_URL, headers=headers,
        json={"upsert_restaurant_overrides": [{"restaurant_id": "00000000-0000-0000-0000-000000000000", "commission_type": "FIXED", "value": "15.00"}]},
    )
    assert response.status_code == 404


def test_remove_restaurant_override(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "2")
    client.patch(
        COMMISSIONS_URL, headers=headers,
        json={"upsert_restaurant_overrides": [{"restaurant_id": str(restaurant.id), "commission_type": "FIXED", "value": "15.00"}]},
    )

    response = client.patch(COMMISSIONS_URL, headers=headers, json={"remove_restaurant_override_ids": [str(restaurant.id)]})
    assert response.status_code == 200
    assert response.json()["restaurant_overrides"] == []


def test_update_requires_at_least_one_change(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(COMMISSIONS_URL, headers=headers, json={})
    assert response.status_code == 422


# --------------------------- Order snapshot integration ---------------------------


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _seed_order_scenario(seed):
    owner = User(name="Owner P17", email="owner-order-p17@example.com", phone="8000000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Cust P17", email="cust-order-p17@example.com", phone="8000000021", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    seed.add_all([owner, customer])
    seed.commit()

    restaurant = Restaurant(
        owner_id=owner.id, name="Diner P17", phone="9876500001", address="Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    seed.add(restaurant)
    seed.commit()

    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("200.00"))
    seed.add(product)
    seed.commit()

    address = create_address(seed, customer.id, {
        "label": "Home", "recipient_name": "Cust P17", "phone": "8000000021",
        "address_line": "1 Road", "city": "Testville", "state": "TS", "postal_code": "999000",
    })

    return {
        "restaurant_id": str(restaurant.id),
        "customer_token": create_access_token(customer.id),
        "product_id": str(product.id),
        "address_id": str(address.id),
    }


def _place_order(client, scenario):
    client.post("/api/v1/customer/cart/items", headers={"Authorization": f"Bearer {scenario['customer_token']}"}, json={"product_id": scenario["product_id"], "quantity": 1})
    return client.post(
        "/api/v1/customer/orders",
        headers={"Authorization": f"Bearer {scenario['customer_token']}"},
        json={"address_id": scenario["address_id"]},
    )


def _admin_headers_for_engine(engine):
    with Session(engine) as db:
        admin = User(name="Admin P17", email="admin-order-p17@example.com", phone="8000000030", password_hash=hash_password("x"), role=UserRole.ADMIN)
        db.add(admin)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _get_order_from_db(engine, order_id: str) -> Order:
    with Session(engine) as db:
        return db.get(Order, UUID(order_id))


def test_order_has_no_commission_when_nothing_configured(engine):
    with Session(engine) as seed:
        scenario = _seed_order_scenario(seed)

    with TestClient(app) as client:
        response = _place_order(client, scenario)
        assert response.status_code == 201
        order = _get_order_from_db(engine, response.json()["id"])
        assert order.commission_type is None
        assert order.commission_amount is None


def test_order_snapshots_percentage_default_commission(engine):
    with Session(engine) as seed:
        scenario = _seed_order_scenario(seed)
    admin_headers = _admin_headers_for_engine(engine)

    with TestClient(app) as client:
        client.patch("/api/v1/admin/commissions", headers=admin_headers, json={"default": {"commission_type": "PERCENTAGE", "value": "10.00"}})
        response = _place_order(client, scenario)
        assert response.status_code == 201
        order = _get_order_from_db(engine, response.json()["id"])
        assert order.commission_type == "PERCENTAGE"
        assert order.commission_rate == Decimal("10.00")
        # subtotal is 200.00 (one item at 200.00) -> 10% = 20.00
        assert order.commission_amount == Decimal("20.00")


def test_restaurant_override_takes_precedence_over_default(engine):
    with Session(engine) as seed:
        scenario = _seed_order_scenario(seed)
    admin_headers = _admin_headers_for_engine(engine)

    with TestClient(app) as client:
        client.patch("/api/v1/admin/commissions", headers=admin_headers, json={"default": {"commission_type": "PERCENTAGE", "value": "10.00"}})
        client.patch(
            "/api/v1/admin/commissions", headers=admin_headers,
            json={"upsert_restaurant_overrides": [{"restaurant_id": scenario["restaurant_id"], "commission_type": "FIXED", "value": "50.00"}]},
        )
        response = _place_order(client, scenario)
        order = _get_order_from_db(engine, response.json()["id"])
        assert order.commission_type == "FIXED"
        assert order.commission_amount == Decimal("50.00")


def test_changing_the_rule_never_alters_an_already_placed_orders_commission(engine):
    """The core guarantee this phase exists to protect: 'do not
    retroactively change historical order financial calculations.'"""
    with Session(engine) as seed:
        scenario = _seed_order_scenario(seed)
    admin_headers = _admin_headers_for_engine(engine)

    with TestClient(app) as client:
        client.patch("/api/v1/admin/commissions", headers=admin_headers, json={"default": {"commission_type": "PERCENTAGE", "value": "10.00"}})
        first_order_id = _place_order(client, scenario).json()["id"]
        first_order = _get_order_from_db(engine, first_order_id)
        assert first_order.commission_amount == Decimal("20.00")

        # Admin changes the rule dramatically after the order was placed.
        client.patch("/api/v1/admin/commissions", headers=admin_headers, json={"default": {"commission_type": "FIXED", "value": "999.00"}})

        # Re-read the SAME, already-placed order — its snapshot must be untouched.
        first_order_after_change = _get_order_from_db(engine, first_order_id)
        assert first_order_after_change.commission_type == "PERCENTAGE"
        assert first_order_after_change.commission_amount == Decimal("20.00")

        # A brand-new order placed after the change gets the NEW rule.
        second_order_id = _place_order(client, scenario).json()["id"]
        second_order = _get_order_from_db(engine, second_order_id)
        assert second_order.commission_type == "FIXED"
        assert second_order.commission_amount == Decimal("999.00")
