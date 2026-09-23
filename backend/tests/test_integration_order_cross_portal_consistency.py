"""Integration Phase 5 — Order Creation Integration.

One order, placed once by a customer, must be the *same database record*
when read back through every portal that can see it: Customer, Restaurant,
Admin, and (once assigned) Rider. This file places a single order and reads
it back through all four surfaces, cross-checking the exact fields the
phase calls out — customer identity, restaurant identity, items, prices,
address, payment method, total, status, and created time — never allowing
any portal's view to drift from another's.
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
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
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


def test_one_order_is_the_same_record_across_customer_restaurant_admin_and_rider(engine):
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-p5@example.com", phone="9400000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Priya Nair", email="priya-p5@example.com", phone="9400000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        rider = User(name="Rider One", email="rider-p5@example.com", phone="9400000003", password_hash=hash_password("x"), role=UserRole.RIDER)
        admin = User(name="Admin One", email="admin-p5@example.com", phone="9400000004", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, customer, rider, admin])
        seed.commit()
        # Rider Assignment Integration — admin's assign-rider now requires
        # the rider to be an approved delivery partner.
        seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
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
        product_id, restaurant_id = product.id, restaurant.id

        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Priya Nair", "phone": "9400000002",
            "address_line": "7 Lake View Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560002",
        })
        address_id = address.id

        customer_id = customer.id
        customer_token = create_access_token(customer.id)
        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)
        rider_token = create_access_token(rider.id)
        rider_id = rider.id

    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    rider_headers = {"Authorization": f"Bearer {rider_token}"}

    with TestClient(app) as client:
        add_item_resp = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers,
            json={"product_id": str(product_id), "quantity": 3},
        )
        assert add_item_resp.status_code == 201

        place_resp = client.post(
            "/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)},
        )
        assert place_resp.status_code == 201
        order_id = place_resp.json()["id"]

        # ---- Customer & Restaurant both use OrderRead: values must be byte-identical ----
        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers).json()
        restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers).json()

        for field in (
            "id", "user_id", "restaurant_id", "order_number", "status", "payment_method",
            "subtotal", "delivery_fee", "tax", "discount", "total", "item_count",
            "address_line", "city", "state", "postal_code",
            "created_at", "customer_name", "customer_email", "customer_phone",
        ):
            assert customer_view[field] == restaurant_view[field], f"{field} drifted between customer and restaurant views"

        assert customer_view["user_id"] == str(customer_id)
        assert customer_view["restaurant_id"] == str(restaurant_id)
        assert len(customer_view["items"]) == len(restaurant_view["items"]) == 1
        assert customer_view["items"][0]["product_id"] == restaurant_view["items"][0]["product_id"] == str(product_id)
        assert customer_view["items"][0]["unit_price"] == restaurant_view["items"][0]["unit_price"] == "40.00"
        assert customer_view["items"][0]["quantity"] == restaurant_view["items"][0]["quantity"] == 3
        assert customer_view["subtotal"] == "120.00"
        assert customer_view["total"] == "150.00"

        # ---- Admin's own view (differently shaped, but must carry the same values) ----
        admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers).json()
        assert admin_view["id"] == customer_view["id"]
        assert admin_view["order_number"] == customer_view["order_number"]
        assert admin_view["customer_name"] == customer_view["customer_name"]
        assert admin_view["customer_email"] == customer_view["customer_email"]
        assert admin_view["customer_phone"] == customer_view["customer_phone"]
        assert admin_view["restaurant_name"] == customer_view["restaurant_name"]
        assert admin_view["status"] == customer_view["status"]
        assert admin_view["payment_method"] == customer_view["payment_method"]
        assert admin_view["subtotal"] == customer_view["subtotal"]
        assert admin_view["delivery_fee"] == customer_view["delivery_fee"]
        assert admin_view["tax"] == customer_view["tax"]
        assert admin_view["discount"] == customer_view["discount"]
        assert admin_view["total"] == customer_view["total"]
        assert admin_view["created_at"] == customer_view["created_at"]
        assert len(admin_view["items"]) == 1
        assert admin_view["items"][0]["product_name"] == restaurant_view["items"][0]["product_name"]
        assert admin_view["items"][0]["unit_price"] == restaurant_view["items"][0]["unit_price"]
        assert admin_view["items"][0]["quantity"] == restaurant_view["items"][0]["quantity"]

        # ---- Advance the order and assign a rider through the real admin endpoint ----
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers).status_code == 200

        assign_resp = client.patch(
            f"/api/v1/admin/orders/{order_id}/assign-rider", headers=admin_headers,
            json={"rider_id": str(rider_id), "reason": "Nearest available rider"},
        )
        assert assign_resp.status_code == 200

        customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers=customer_headers).json()
        restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers).json()
        admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers).json()
        rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers).json()

        # ---- Status must agree everywhere after the assignment ----
        assert customer_view["status"] == restaurant_view["status"] == admin_view["status"] == rider_view["status"] == "rider_assigned"
        assert customer_view["rider_id"] == restaurant_view["rider_id"] == str(rider_id)
        assert admin_view["rider_name"] == "Rider One"

        # ---- Rider's view: same order identity, prices, items, address, payment method ----
        assert rider_view["order_id"] == order_id
        assert rider_view["order_number"] == customer_view["order_number"]
        assert rider_view["restaurant_name"] == customer_view["restaurant_name"]
        assert rider_view["customer_name"] == customer_view["customer_name"]
        assert rider_view["subtotal"] == customer_view["subtotal"]
        assert rider_view["delivery_fee"] == customer_view["delivery_fee"]
        assert rider_view["total"] == customer_view["total"]
        assert rider_view["payment_method"] == customer_view["payment_method"]
        assert rider_view["created_at"] == customer_view["created_at"]
        assert rider_view["delivery_address_line"] == customer_view["address_line"]
        assert rider_view["delivery_city"] == customer_view["city"]
        assert rider_view["delivery_postal_code"] == customer_view["postal_code"]
        assert len(rider_view["items"]) == 1
        assert rider_view["items"][0]["product_name"] == customer_view["items"][0]["product_name"]
        assert rider_view["items"][0]["unit_price"] == customer_view["items"][0]["unit_price"]
        assert rider_view["items"][0]["quantity"] == customer_view["items"][0]["quantity"]
