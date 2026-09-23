"""Phase 18 — Customer <-> Restaurant integration tests.

Five complete real-world flows, each exercised through real HTTP calls on
both sides (TestClient) — the actual customer-facing and restaurant-facing
endpoints, never a direct service-layer call — so every test here exercises
the exact same code path a real customer app and a real restaurant-owner
browser tab would:

  Test 1 — Successful order: PLACED -> CONFIRMED -> PREPARING -> READY_FOR_PICKUP,
           re-read from the customer's own endpoints at every step.
  Test 2 — Restaurant rejection: the customer must see REJECTED and get notified.
  Test 3 — Restaurant closed: a closed restaurant must refuse a new order.
  Test 4 — Product unavailable: the customer must not be able to order it.
  Test 5 — Owner isolation: two owners, two restaurants, no cross-access.
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
from app.models import Product, Restaurant, User, UserRole
from app.services.addresses import create_address


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


def _seed_owner_and_restaurant(seed, owner_email="owner@example.com", owner_phone="9000000001", name="Chai House"):
    owner = User(
        name="Owner", email=owner_email, phone=owner_phone,
        password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER,
    )
    seed.add(owner)
    seed.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=name, phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    seed.add(restaurant)
    seed.commit()
    return owner, restaurant


def _seed_customer_with_address(seed, email="priya@example.com", phone="9222222222"):
    customer = User(
        name="Priya Nair", email=email, phone=phone,
        password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER,
    )
    seed.add(customer)
    seed.commit()
    address = create_address(seed, customer.id, {
        "label": "Home", "recipient_name": "Priya Nair", "phone": phone,
        "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
    })
    return customer, address


# --------------------------- Test 1 — Successful order ---------------------------


def test_full_placed_to_ready_flow_is_visible_on_both_sides(engine):
    with Session(engine) as seed:
        owner = User(
            name="Owner", email="owner@example.com", phone="9000000001",
            password_hash=hash_password("Passw0rd!"), role=UserRole.RESTAURANT_OWNER,
        )
        customer = User(
            name="Priya Nair", email="priya@example.com", phone="9222222222",
            password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER,
        )
        seed.add_all([owner, customer])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id = product.id
        restaurant_id = restaurant.id

        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Priya Nair", "phone": "9222222222",
            "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
        })
        address_id = address.id

        owner_token = create_access_token(owner.id)
        customer_token = create_access_token(customer.id)

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        # --- Customer places the order through the real checkout path ---
        add_item_resp = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": str(product_id), "quantity": 2},
        )
        assert add_item_resp.status_code == 201

        place_resp = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)},
        )
        assert place_resp.status_code == 201
        order = place_resp.json()
        order_id = order["id"]
        assert order["status"] == "placed"
        assert order["total"] == "110.00"  # 2 * 40 + 30 delivery fee

        # --- Restaurant sees it land in the incoming-orders queue ---
        incoming = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
        assert incoming.status_code == 200
        assert len(incoming.json()) == 1
        assert incoming.json()[0]["id"] == order_id

        # --- Restaurant accepts -> customer side must reflect it immediately ---
        accept_resp = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        assert accept_resp.status_code == 200
        assert accept_resp.json()["status"] == "confirmed"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.status_code == 200
        assert customer_view.json()["status"] == "confirmed"

        filtered_list = client.get("/api/v1/customer/orders?status=confirmed", headers=customer_headers)
        assert filtered_list.status_code == 200
        assert len(filtered_list.json()) == 1
        assert filtered_list.json()[0]["id"] == order_id

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.status_code == 200
        assert tracking.json()["order_status"] == "confirmed"
        assert [h["status"] for h in tracking.json()["status_history"]] == ["placed", "confirmed"]

        notifications = client.get("/api/v1/customer/notifications", headers=customer_headers)
        assert notifications.status_code == 200
        assert any(n["type"] == "order_confirmed" and n["order_id"] == order_id for n in notifications.json())

        # --- Restaurant starts preparing -> customer side updates again ---
        preparing_resp = client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        assert preparing_resp.status_code == 200
        assert preparing_resp.json()["status"] == "preparing"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.json()["status"] == "preparing"

        notifications = client.get("/api/v1/customer/notifications", headers=customer_headers)
        assert any(n["type"] == "order_preparing" and n["order_id"] == order_id for n in notifications.json())

        # --- Restaurant marks ready -> customer side reaches the final state
        #     for this flow (rider assignment is a separate, later phase) ---
        ready_resp = client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        assert ready_resp.status_code == 200
        assert ready_resp.json()["status"] == "ready_for_pickup"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.status_code == 200
        assert customer_view.json()["status"] == "ready_for_pickup"

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "ready_for_pickup"
        assert tracking.json()["assignment_status"] == "unassigned"  # no rider yet — that's a later phase
        assert [h["status"] for h in tracking.json()["status_history"]] == [
            "placed", "confirmed", "preparing", "ready_for_pickup",
        ]

        notifications = client.get("/api/v1/customer/notifications", headers=customer_headers)
        assert any(n["type"] == "order_ready" and n["order_id"] == order_id for n in notifications.json())

        filtered_list = client.get("/api/v1/customer/orders?status=ready_for_pickup", headers=customer_headers)
        assert len(filtered_list.json()) == 1
        assert filtered_list.json()[0]["id"] == order_id

        # Sanity: the order no longer shows up in the restaurant's "pending" bucket,
        # and now shows up in "ready" — confirms both portals agree on the same state.
        pending_now = client.get("/api/v1/restaurant/orders?status=pending", headers=owner_headers)
        assert pending_now.json() == []
        ready_now = client.get("/api/v1/restaurant/orders?status=ready", headers=owner_headers)
        assert len(ready_now.json()) == 1
        assert ready_now.json()[0]["id"] == order_id


# --------------------------- Test 2 — Restaurant rejection ---------------------------


def test_customer_sees_rejection_and_gets_notified(engine):
    with Session(engine) as seed:
        owner, restaurant = _seed_owner_and_restaurant(seed)
        customer, address = _seed_customer_with_address(seed)
        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id, address_id = product.id, address.id
        owner_token = create_access_token(owner.id)
        customer_token = create_access_token(customer.id)

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": str(product_id), "quantity": 1},
        )
        place_resp = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)},
        )
        order_id = place_resp.json()["id"]

        reject_resp = client.post(
            f"/api/v1/restaurant/orders/{order_id}/reject",
            headers=owner_headers,
            json={"reason": "Out of stock for this item"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["status"] == "rejected"

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers)
        assert customer_view.status_code == 200
        assert customer_view.json()["status"] == "rejected"
        assert customer_view.json()["cancelled_reason"] == "Out of stock for this item"

        tracking = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=customer_headers)
        assert tracking.json()["order_status"] == "rejected"
        assert [h["status"] for h in tracking.json()["status_history"]] == ["placed", "rejected"]

        notifications = client.get("/api/v1/customer/notifications", headers=customer_headers)
        order_notices = [n for n in notifications.json() if n["order_id"] == order_id]
        assert any(n["type"] == "order_placed" for n in order_notices)
        rejection_notice = next((n for n in order_notices if n["type"] == "order_rejected"), None)
        assert rejection_notice is not None
        assert "unable to accept" in rejection_notice["body"]

        filtered_list = client.get("/api/v1/customer/orders?status=rejected", headers=customer_headers)
        assert len(filtered_list.json()) == 1
        assert filtered_list.json()[0]["id"] == order_id


# --------------------------- Test 3 — Restaurant closed ---------------------------


def test_customer_cannot_place_order_when_restaurant_is_closed(engine):
    with Session(engine) as seed:
        owner, restaurant = _seed_owner_and_restaurant(seed)
        restaurant.is_open = False
        seed.commit()
        customer, address = _seed_customer_with_address(seed)
        product = Product(restaurant_id=restaurant.id, name="Masala Chai", price=Decimal("40.00"))
        seed.add(product)
        seed.commit()
        product_id, address_id = product.id, address.id
        customer_token = create_access_token(customer.id)

    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        # Adding to cart is still allowed (the product itself is fine) — the
        # gate is enforced at checkout, same as an out-of-hours restaurant.
        add_resp = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": str(product_id), "quantity": 1},
        )
        assert add_resp.status_code == 201

        place_resp = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)},
        )
        assert place_resp.status_code == 422
        assert "closed" in place_resp.json()["detail"].lower()

        # The checkout preview must also warn about it up front, not just fail silently at the last step.
        preview = client.get("/api/v1/customer/checkout", headers=customer_headers)
        assert preview.status_code == 200
        assert any("closed" in issue.lower() for issue in preview.json()["issues"])


# --------------------------- Test 4 — Product unavailable ---------------------------


def test_customer_cannot_order_an_unavailable_product(engine):
    with Session(engine) as seed:
        owner, restaurant = _seed_owner_and_restaurant(seed)
        customer, _address = _seed_customer_with_address(seed)
        product = Product(
            restaurant_id=restaurant.id, name="Sold Out Special", price=Decimal("40.00"), is_available=False,
        )
        seed.add(product)
        seed.commit()
        product_id = product.id
        restaurant_id = restaurant.id
        customer_token = create_access_token(customer.id)

    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        add_resp = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": str(product_id), "quantity": 1},
        )
        # The product is filtered out of the customer-visible catalog entirely —
        # attempting to add it fails before an order can ever be placed from it.
        assert add_resp.status_code == 404

        # It also never appears in the restaurant's public product listing.
        public_products = client.get(f"/api/v1/customer/restaurants/{restaurant_id}/products")
        assert public_products.status_code == 200
        assert all(p["id"] != str(product_id) for p in public_products.json())


# --------------------------- Test 5 — Owner isolation ---------------------------


def test_owner_isolation_between_two_restaurants(engine):
    with Session(engine) as seed:
        owner_a, restaurant_a = _seed_owner_and_restaurant(seed, "ownera@example.com", "9111111111", "A's Diner")
        owner_b, restaurant_b = _seed_owner_and_restaurant(seed, "ownerb@example.com", "9333333333", "B's Diner")
        restaurant_a_id, restaurant_b_id = restaurant_a.id, restaurant_b.id
        token_a = create_access_token(owner_a.id)
        token_b = create_access_token(owner_b.id)

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    with TestClient(app) as client:
        # Owner A -> A: allowed.
        resp = client.get("/api/v1/restaurant/profile", headers=headers_a)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(restaurant_a_id)

        # Owner A -> B: refused.
        resp = client.get(f"/api/v1/restaurant/profile?restaurant_id={restaurant_b_id}", headers=headers_a)
        assert resp.status_code == 403

        # Owner B -> B: allowed.
        resp = client.get("/api/v1/restaurant/profile", headers=headers_b)
        assert resp.status_code == 200
        assert resp.json()["id"] == str(restaurant_b_id)

        # Owner B -> A: refused.
        resp = client.get(f"/api/v1/restaurant/profile?restaurant_id={restaurant_a_id}", headers=headers_b)
        assert resp.status_code == 403
