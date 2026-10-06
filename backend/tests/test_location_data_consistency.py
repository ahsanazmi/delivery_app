"""Maps & Location System Phase 31 — Location Data Consistency.

Customer Address -> Order Address Snapshot -> Rider Delivery -> Admin
Order: all four must refer to the same, correct delivery location — and
editing the customer's saved address afterward must not change any of
them. This extends Phase 12's own immutability test (which only checked
the customer's own order read) to prove the same guarantee holds across
every role that reads an order's delivery location.
"""

from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


def test_customer_rider_and_admin_all_see_the_same_snapshotted_location_and_none_of_them_change_when_the_address_is_edited():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = User(name="Priya", email="consistency-cust@example.com", phone="9800000001", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
            owner = User(name="Owner", email="consistency-owner@example.com", phone="9800000002", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
            rider = User(name="Rider", email="consistency-rider@example.com", phone="9800000003", password_hash=hash_password("x"), role=UserRole.RIDER)
            admin = User(name="Admin", email="consistency-admin@example.com", phone="9800000004", password_hash=hash_password("x"), role=UserRole.ADMIN)
            seed.add_all([customer, owner, rider, admin])
            seed.commit()
            seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))

            restaurant = Restaurant(
                owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
                latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
            )
            seed.add(restaurant)
            seed.commit()
            product = Product(restaurant_id=restaurant.id, name="Biryani", price=Decimal("220.00"))
            seed.add(product)
            seed.commit()

            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home", "recipient_name": "Priya", "phone": "9800000001",
                "address_line": "15 Market Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "landmark": "Near bus stand", "latitude": Decimal("12.9716"), "longitude": Decimal("77.5946"),
                "place_id": "N:original-consistency",
            })
            order = create_order(seed, customer, address.id)
            order.rider_id = rider.id
            order.status = OrderStatus.OUT_FOR_DELIVERY
            seed.commit()

            customer_token = create_access_token(customer.id)
            rider_token = create_access_token(rider.id)
            admin_token = create_access_token(admin.id)
            order_id, address_id = order.id, address.id

        with TestClient(app) as client:
            def fetch_all():
                customer_view = client.get(f"/api/v1/customer/orders/{order_id}", headers={"Authorization": f"Bearer {customer_token}"}).json()
                rider_view = client.get(f"/api/v1/rider/deliveries/{order_id}", headers={"Authorization": f"Bearer {rider_token}"}).json()
                admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers={"Authorization": f"Bearer {admin_token}"}).json()
                return customer_view, rider_view, admin_view

            def assert_consistent(customer_view, rider_view, admin_view, *, address_line, landmark, latitude, longitude):
                assert customer_view["address_line"] == rider_view["delivery_address_line"] == admin_view["address_line"] == address_line
                assert customer_view["landmark"] == rider_view["delivery_landmark"] == admin_view["landmark"] == landmark
                assert Decimal(str(customer_view["latitude"])) == Decimal(str(rider_view["delivery_latitude"])) == Decimal(str(admin_view["latitude"])) == latitude
                assert Decimal(str(customer_view["longitude"])) == Decimal(str(rider_view["delivery_longitude"])) == Decimal(str(admin_view["longitude"])) == longitude

            before = fetch_all()
            assert_consistent(*before, address_line="15 Market Road", landmark="Near bus stand", latitude=Decimal("12.9716"), longitude=Decimal("77.5946"))

            # The customer moves — editing the very address the order was placed against.
            update = client.patch(
                f"/api/v1/addresses/{address_id}",
                headers={"Authorization": f"Bearer {customer_token}"},
                json={"address_line": "99 New Layout", "landmark": "Near the new mall", "latitude": 19.0760, "longitude": 72.8777},
            )
            assert update.status_code == 200

            after = fetch_all()
            assert_consistent(*after, address_line="15 Market Road", landmark="Near bus stand", latitude=Decimal("12.9716"), longitude=Decimal("77.5946"))
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
