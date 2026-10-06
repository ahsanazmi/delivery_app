"""Maps & Location System Phase 32 — Location + Order E2E Test.

Customer selects a location, saves an address, browses a restaurant,
checks out (backend validates service area, calculates distance and
delivery fee), places an order (location snapshotted), the restaurant
progresses it, an admin assigns a rider, the rider sees the authorized
destination, and the admin sees the appropriate operational location —
all through real HTTP calls against the real endpoints, then the
database is read back directly to confirm consistency.
"""

from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.service_area import ServiceArea, ServiceAreaPostalCode
from app.models.user import User, UserRole


def test_full_customer_to_admin_location_flow_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = User(name="Priya", email="e2e-cust@example.com", phone="9700000001", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
            owner = User(name="Owner", email="e2e-owner@example.com", phone="9700000002", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
            rider = User(name="Rider", email="e2e-rider@example.com", phone="9700000003", password_hash=hash_password("x"), role=UserRole.RIDER)
            admin = User(name="Admin", email="e2e-admin@example.com", phone="9700000004", password_hash=hash_password("x"), role=UserRole.ADMIN)
            seed.add_all([customer, owner, rider, admin])
            seed.commit()
            seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))

            restaurant = Restaurant(
                owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
                latitude=Decimal("26.068"), longitude=Decimal("83.1836"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
                is_active=True,
            )
            seed.add(restaurant)
            seed.commit()
            product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
            seed.add(product)
            seed.commit()

            # Serviceable zone that covers the customer's own postal code —
            # "backend validates service area" must have something real to check.
            zone = ServiceArea(city="Azamgarh", zone_name="City Zone", is_active=True)
            seed.add(zone)
            seed.commit()
            seed.add(ServiceAreaPostalCode(service_area_id=zone.id, postal_code="276001"))
            seed.commit()

            customer_token = create_access_token(customer.id)
            owner_token = create_access_token(owner.id)
            rider_token = create_access_token(rider.id)
            admin_token = create_access_token(admin.id)
            restaurant_id, product_id = restaurant.id, product.id

        with TestClient(app) as client:
            customer_headers = {"Authorization": f"Bearer {customer_token}"}

            # Customer selects a location and saves an address.
            create_address = client.post(
                "/api/v1/addresses", headers=customer_headers,
                json={
                    "recipient_name": "Priya", "phone": "9700000001", "address_line": "15 Market Road",
                    "city": "Azamgarh", "state": "Uttar Pradesh", "postal_code": "276001",
                    "landmark": "Near bus stand", "latitude": 26.0998, "longitude": 83.1991,
                },
            )
            assert create_address.status_code == 201
            address_id = create_address.json()["id"]

            # Browses the restaurant.
            restaurant_list = client.get("/api/v1/customer/restaurants", headers=customer_headers)
            assert restaurant_list.status_code == 200
            assert any(r["id"] == str(restaurant_id) for r in restaurant_list.json())

            add_item = client.post(
                "/api/v1/customer/cart/items", headers=customer_headers,
                json={"product_id": str(product_id), "quantity": 1},
            )
            assert add_item.status_code in (200, 201)

            # Checkout preview — service area validated, distance calculated.
            preview = client.get("/api/v1/customer/checkout", headers=customer_headers)
            assert preview.status_code == 200
            preview_body = preview.json()
            assert preview_body["issues"] == []
            assert preview_body["distance_km"] is not None

            # Order validation and creation — delivery fee is the backend's
            # own flat, restaurant-configured figure, never client-supplied.
            validate = client.post(
                "/api/v1/customer/orders/validate", headers=customer_headers, json={"address_id": address_id}
            )
            assert validate.status_code == 200
            assert validate.json()["valid"] is True
            assert validate.json()["delivery_fee"] == "30.00"

            create = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
            assert create.status_code == 201
            order = create.json()
            order_id = order["id"]
            assert order["address_line"] == "15 Market Road"
            assert order["landmark"] == "Near bus stand"
            assert Decimal(str(order["latitude"])) == Decimal("26.0998")
            assert Decimal(str(order["longitude"])) == Decimal("83.1991")
            assert order["delivery_fee"] == "30.00"

            # Restaurant sees the order and progresses it.
            owner_headers = {"Authorization": f"Bearer {owner_token}"}
            restaurant_view = client.get(f"/api/v1/restaurant/orders/{order_id}", headers=owner_headers)
            assert restaurant_view.status_code == 200
            assert restaurant_view.json()["order_number"] == order["order_number"]

            assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers).status_code == 200
            assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers).status_code == 200

            # Admin assigns a rider.
            admin_headers = {"Authorization": f"Bearer {admin_token}"}
            assign = client.patch(
                f"/api/v1/admin/orders/{order_id}/assign-rider", headers=admin_headers,
                json={"rider_id": str(rider.id), "reason": "Nearest available rider"},
            )
            assert assign.status_code == 200

            # Rider sees the authorized destination (their own assigned delivery only).
            rider_headers = {"Authorization": f"Bearer {rider_token}"}
            rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers=rider_headers)
            assert rider_view.status_code == 200
            rider_body = rider_view.json()
            assert rider_body["delivery_address_line"] == "15 Market Road"
            assert Decimal(str(rider_body["delivery_latitude"])) == Decimal("26.0998")

            # Admin sees the appropriate operational location, including
            # which service area it falls under.
            admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
            assert admin_view.status_code == 200
            admin_body = admin_view.json()
            assert admin_body["address_line"] == "15 Market Road"
            assert admin_body["service_area_zone_name"] == "City Zone"

        # Verify database consistency directly, independent of any endpoint.
        with Session(engine) as verify:
            db_order = verify.get(Order, UUID(order_id))
            assert db_order.address_line == "15 Market Road"
            assert db_order.landmark == "Near bus stand"
            assert db_order.latitude == Decimal("26.0998000")
            assert db_order.longitude == Decimal("83.1991000")
            assert str(db_order.rider_id) == str(rider.id)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
