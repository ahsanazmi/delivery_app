from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.order import OrderStatus
from app.models.review import Review
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import assign_rider_to_order, create_order, transition_order_status


@pytest.fixture()
def harness():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine, autoflush=False) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield engine
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def _seed_delivered_order(engine):
    with Session(engine) as seed:
        customer = User(name="Customer", email="customer@example.com", password_hash="x", role=UserRole.CUSTOMER)
        other_restaurant_owner = User(name="Other Owner", email="other-owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
        attacker_restaurant_owner = User(name="Attacker Owner", email="attacker-owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
        rider = User(name="Rider", email="rider@example.com", password_hash="x", role=UserRole.RIDER)
        attacker_rider = User(name="Attacker Rider", email="attacker-rider@example.com", password_hash="x", role=UserRole.RIDER)
        seed.add_all([customer, other_restaurant_owner, attacker_restaurant_owner, rider, attacker_rider])
        seed.commit()

        real_restaurant = Restaurant(
            owner_id=other_restaurant_owner.id, name="Real Restaurant", phone="9876543210",
            address="Main Road", latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        decoy_restaurant = Restaurant(
            owner_id=attacker_restaurant_owner.id, name="Decoy Restaurant", phone="9876500000",
            address="Side Street", latitude=Decimal("13.1"), longitude=Decimal("78.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        seed.add_all([real_restaurant, decoy_restaurant])
        seed.commit()

        product = Product(restaurant_id=real_restaurant.id, name="Item", price=Decimal("100.00"))
        seed.add(product)
        seed.commit()

        cart = create_cart_for_user(seed, customer.id)
        add_item(seed, cart, product.id, 1)
        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
            "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
        })
        order = create_order(seed, customer, address.id)
        transition_order_status(seed, order, OrderStatus.CONFIRMED)
        assign_rider_to_order(seed, order, rider.id)
        transition_order_status(seed, order, OrderStatus.PICKED_UP)
        transition_order_status(seed, order, OrderStatus.OUT_FOR_DELIVERY)
        transition_order_status(seed, order, OrderStatus.DELIVERED)
        seed.commit()

        return {
            "token": create_access_token(customer.id),
            "customer_id": customer.id,
            "order_id": order.id,
            "real_restaurant_id": real_restaurant.id,
            "decoy_restaurant_id": decoy_restaurant.id,
            "rider_id": rider.id,
            "attacker_rider_id": attacker_rider.id,
        }


def test_smuggled_ownership_fields_are_rejected_by_the_schema(harness):
    engine = harness
    seeded = _seed_delivered_order(engine)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {seeded['token']}"}
        response = client.post(
            f"/api/v1/customer/orders/{seeded['order_id']}/review",
            headers=headers,
            json={
                "restaurant_rating": 5,
                "delivery_rating": 5,
                "comment": "Great",
                # every one of these is an attempt to smuggle trusted
                # ownership data through the request body
                "order_id": str(uuid4()),
                "customer_id": str(uuid4()),
                "restaurant_id": str(seeded["decoy_restaurant_id"]),
                "rider_id": str(seeded["attacker_rider_id"]),
            },
        )
        assert response.status_code == 422


def test_review_is_always_attributed_to_the_order_s_real_restaurant_and_rider(harness):
    """Even without the extra="forbid" schema hardening, create_order_review
    has no parameter through which a client-supplied restaurant_id or
    rider_id could reach the database — it derives both exclusively from
    the verified order. This proves that end to end over real HTTP: the
    stored review matches the order's real restaurant/rider, never
    anything a client could have supplied."""
    engine = harness
    seeded = _seed_delivered_order(engine)

    with TestClient(app) as client:
        headers = {"Authorization": f"Bearer {seeded['token']}"}
        response = client.post(
            f"/api/v1/customer/orders/{seeded['order_id']}/review",
            headers=headers,
            json={"restaurant_rating": 5, "delivery_rating": 5, "comment": "Great"},
        )
        assert response.status_code == 201
        review_id = UUID(response.json()["id"])

    with Session(engine) as verify:
        stored = verify.query(Review).filter(Review.id == review_id).first()
        assert stored.user_id == seeded["customer_id"]
        assert stored.order_id == seeded["order_id"]
        assert stored.restaurant_id == seeded["real_restaurant_id"]
        assert stored.restaurant_id != seeded["decoy_restaurant_id"]
        assert stored.rider_id == seeded["rider_id"]
        assert stored.rider_id != seeded["attacker_rider_id"]
