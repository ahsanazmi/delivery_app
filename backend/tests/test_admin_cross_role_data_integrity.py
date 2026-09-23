"""Admin Portal — Phase 26: Cross-Role Data Integrity.

Verifies that all four roles (Customer, Rider, Restaurant Owner, Admin)
read and write the exact same underlying rows — never a parallel
"admin's own copy" of a customer, restaurant, rider, or order. Every
assertion here compares a real primary-key id obtained through one role's
own HTTP endpoint against the id the Admin Portal's endpoints return for
"the same" thing, and separately proves row counts never grow just
because admin looked at (or acted on) a record.

    User            -> Customer / Rider / Restaurant Owner / Admin, one
                       table distinguished only by `role`.
    Restaurant      -> Owner (User.id), Categories (Category, platform-
                       wide) / MenuCategory (restaurant-scoped), Products,
                       Orders — all the same rows the Restaurant Owner
                       Portal itself manages.
    Order           -> Customer (user_id), Restaurant (restaurant_id
                       snapshot), Payment (order_id FK), DeliveryAssignment
                       (order_id FK).
    DeliveryAssignment -> Rider (rider_id FK to the same users.id).

This is a real end-to-end HTTP flow (TestClient), not a service-layer
shortcut — the same style test_integration_customer_restaurant_rider_full_
lifecycle.py already established, extended here with the Admin Portal's
own read endpoints checked at each step.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    AdminAuditLog,
    ApprovalStatus,
    DeliveryAssignment,
    DeliveryPartner,
    Order,
    Payment,
    PaymentProvider,
    PaymentStatus,
    PlatformSettings,
    Product,
    Restaurant,
    RiderSettlement,
    User,
    UserRole,
)


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


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# --------------------------------------------------------------------
# 1. No "Admin"-only shadow model exists for any of the four core entities
# --------------------------------------------------------------------


def test_no_admin_only_shadow_model_exists_for_a_core_entity():
    """Static check over the whole model registry: every table admin
    could plausibly need already exists for another role's own use
    (users, restaurants, orders, payments, delivery_assignments,
    products, categories, delivery_partners, ...). The only tables that
    exist purely because of the Admin Portal are AdminAuditLog (a log of
    admin actions — not a copy of any entity it acts on) and
    PlatformSettings (a single configuration row with no analog in any
    other role's data at all) — both genuinely new concepts, not stand-ins
    for Customer/Rider/Restaurant/Order."""
    import app.models as models_module

    model_names = {
        name for name in dir(models_module)
        if isinstance(getattr(models_module, name), type) and hasattr(getattr(models_module, name), "__tablename__")
    }
    admin_named = {name for name in model_names if name.lower().startswith("admin")}
    assert admin_named == {"AdminAuditLog"}

    # PlatformSettings has no FK to, or duplicate copy of, any per-user or
    # per-order data — just scalar configuration fields.
    fk_targets = {
        col.target_fullname for col in PlatformSettings.__table__.foreign_keys
    }
    assert fk_targets == set()


# --------------------------------------------------------------------
# 2. User: one table, one row per person, shared by every role's view
# --------------------------------------------------------------------


def test_user_table_is_shared_across_all_four_roles_with_no_admin_shadow_rows(engine):
    with TestClient(app) as client:
        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer A", "email": "p26-customer@example.com", "password": "secure-pass-123", "phone": "9200000001", "role": "CUSTOMER"},
        )
        assert register_customer.status_code == 201
        customer_id = register_customer.json()["id"]

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider A", "email": "p26-rider@example.com", "password": "secure-pass-123", "phone": "9200000002", "role": "RIDER"},
        )
        assert register_rider.status_code == 201
        rider_id = register_rider.json()["id"]

        with Session(engine) as db:
            owner = User(name="Owner A", email="p26-owner@example.com", phone="9200000003", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
            admin = User(name="Admin A", email="p26-admin@example.com", phone="9200000004", password_hash=hash_password("x"), role=UserRole.ADMIN)
            db.add_all([owner, admin])
            db.commit()
            owner_id, admin_id = str(owner.id), str(admin.id)
            admin_token = create_access_token(admin.id)
            assert _count(db, User) == 4

        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        customer_detail = client.get(f"/api/v1/admin/customers/{customer_id}", headers=admin_headers)
        assert customer_detail.status_code == 200
        assert customer_detail.json()["id"] == customer_id

        rider_detail = client.get(f"/api/v1/admin/riders/{rider_id}", headers=admin_headers)
        assert rider_detail.status_code == 200
        assert rider_detail.json()["id"] == rider_id

        owner_detail = client.get(f"/api/v1/admin/restaurant-owners/{owner_id}", headers=admin_headers)
        assert owner_detail.status_code == 200
        assert owner_detail.json()["id"] == owner_id

        customers_list = client.get("/api/v1/admin/customers", headers=admin_headers).json()
        assert any(c["id"] == customer_id for c in customers_list["items"])
        riders_list = client.get("/api/v1/admin/riders", headers=admin_headers).json()
        assert any(r["id"] == rider_id for r in riders_list["items"])
        owners_list = client.get("/api/v1/admin/restaurant-owners", headers=admin_headers).json()
        assert any(o["id"] == owner_id for o in owners_list["items"])

        # Reading — repeatedly, via every list and detail endpoint above —
        # must never create a new users row.
        with Session(engine) as db:
            assert _count(db, User) == 4


# --------------------------------------------------------------------
# 3. Restaurant -> Owner / Products / Orders: the same rows the Restaurant
#    Owner Portal itself manages
# --------------------------------------------------------------------


def test_restaurant_owner_products_relationship_is_shared_not_duplicated(engine):
    with Session(engine) as db:
        owner = User(name="Owner B", email="p26-owner-b@example.com", phone="9200000010", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin B", email="p26-admin-b@example.com", phone="9200000011", password_hash=hash_password("x"), role=UserRole.ADMIN)
        db.add_all([owner, admin])
        db.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House B", phone="9876500000", address="Addr",
            latitude=Decimal("12.97"), longitude=Decimal("77.59"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
        )
        db.add(restaurant)
        db.commit()
        product = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
        db.add(product)
        db.commit()
        restaurant_id, owner_id, product_id = str(restaurant.id), str(owner.id), str(product.id)
        admin_token = create_access_token(admin.id)
        assert _count(db, Restaurant) == 1
        assert _count(db, Product) == 1

    with TestClient(app) as client:
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        detail = client.get(f"/api/v1/admin/restaurants/{restaurant_id}", headers=admin_headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["id"] == restaurant_id
        assert body["owner_id"] == owner_id
        assert any(item["id"] == product_id for item in body["menu"])

        owner_detail = client.get(f"/api/v1/admin/restaurant-owners/{owner_id}", headers=admin_headers)
        assert any(r["id"] == restaurant_id for r in owner_detail.json()["restaurants"])

        # Multiple admin reads of the same restaurant must never fork a
        # second row (e.g. via an accidental get-or-create on the read path).
        for _ in range(3):
            client.get(f"/api/v1/admin/restaurants/{restaurant_id}", headers=admin_headers)

    with Session(engine) as db:
        assert _count(db, Restaurant) == 1
        assert _count(db, Product) == 1


# --------------------------------------------------------------------
# 4. Order -> Customer / Restaurant / Payment / DeliveryAssignment, all
#    visible identically (same ids) through the Admin Portal
# --------------------------------------------------------------------


def test_order_payment_and_delivery_assignment_are_the_same_rows_admin_and_everyone_else_see(engine):
    with Session(engine) as seed:
        owner = User(name="Owner C", email="p26-owner-c@example.com", phone="9200000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add(owner)
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House C", phone="9876500001", address="Addr",
            latitude=Decimal("12.97"), longitude=Decimal("77.59"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("35.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("120.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)
        admin = User(name="Admin C", email="p26-admin-c@example.com", phone="9200000021", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add(admin)
        seed.commit()
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer C", "email": "p26-customer-c@example.com", "password": "secure-pass-123", "phone": "9200000022", "role": "CUSTOMER"},
        )
        customer_id = register_customer.json()["id"]
        customer_token = client.post("/api/v1/auth/login", json={"email": "p26-customer-c@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider C", "email": "p26-rider-c@example.com", "password": "secure-pass-123", "phone": "9200000023", "role": "RIDER"},
        )
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p26-rider-c@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        # Rider approval seeded directly — this test is about data
        # integrity across roles, not re-proving Phase 7-9's own
        # onboarding workflow (already covered exhaustively elsewhere).
        with Session(engine) as db:
            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        # ---- CUSTOMER places the order through the real checkout path ----
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer C", "phone": "9200000022",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        address_id = address.json()["id"]
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
        assert place.status_code == 201
        order_id = place.json()["id"]

        # Admin sees the exact same order the instant it exists.
        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.status_code == 200
        assert admin_order.json()["id"] == order_id
        assert admin_order.json()["customer_name"] == "Customer C"
        assert admin_order.json()["restaurant_name"] == "Chai House C"

        # ---- RESTAURANT progresses it ----
        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)

        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.json()["status"] == "ready_for_pickup"

        # ---- RIDER accepts -> a real DeliveryAssignment row exists ----
        rider_accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        assert rider_accept.status_code == 200

        with Session(engine) as db:
            assignment = db.scalar(select(DeliveryAssignment).where(DeliveryAssignment.order_id == UUID(order_id)))
            assert assignment is not None
            assignment_id = str(assignment.id)
            assert str(assignment.rider_id) == rider_id
            assert _count(db, DeliveryAssignment) == 1

        admin_assignment = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment.status_code == 200
        body = admin_assignment.json()
        assert body["order_id"] == order_id
        assert body["rider_id"] == rider_id
        assert body["status"] == "ACCEPTED"

        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.json()["rider_name"] == "Rider C"

        # ---- RIDER completes the delivery, including COD collection ----
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
        cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert cod_collect.status_code == 200
        payment_id = cod_collect.json()["payment_id"]
        client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)

        # Admin's payment view is the exact same Payment row the rider's
        # own collection action created — same id, same amount.
        admin_payment = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers)
        assert admin_payment.status_code == 200
        assert admin_payment.json()["id"] == payment_id
        assert admin_payment.json()["order_id"] == order_id
        assert Decimal(admin_payment.json()["amount"]) == Decimal("155.00")

        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.json()["status"] == "delivered"
        assert admin_order.json()["payment_status"] == "paid"

        admin_assignment = client.get(f"/api/v1/admin/delivery-assignments/{assignment_id}", headers=admin_headers)
        assert admin_assignment.json()["status"] == "DELIVERED"

    # Exactly one of each real row for this one order — never duplicated
    # by any of the admin reads along the way.
    with Session(engine) as db:
        assert _count(db, Order) == 1
        assert _count(db, Payment) == 1
        assert _count(db, DeliveryAssignment) == 1
        assert db.get(Order, UUID(order_id)).id is not None


# --------------------------------------------------------------------
# 5. Admin write actions create only the new record they're documented to
#    create (an audit-log entry, a settlement) — never a duplicate of the
#    entity being acted on.
# --------------------------------------------------------------------


def test_admin_actions_never_duplicate_the_core_entity_they_act_on(client):
    """client fixture (sqlite, per-test) from conftest.py — a lighter,
    faster harness than the full TestClient(app) engine fixture above,
    appropriate here since this test only exercises admin-side actions
    against directly-seeded data, not a multi-role HTTP handoff."""
    db = next(client.app.dependency_overrides[get_db]())

    admin = User(name="Admin D", email="p26-admin-d@example.com", phone="9200000030", password_hash=hash_password("x"), role=UserRole.ADMIN)
    customer = User(name="Customer D", email="p26-customer-d@example.com", phone="9200000031", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    owner = User(name="Owner D", email="p26-owner-d@example.com", phone="9200000032", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    rider_a = User(name="Rider D1", email="p26-rider-d1@example.com", phone="9200000033", password_hash=hash_password("x"), role=UserRole.RIDER)
    rider_b = User(name="Rider D2", email="p26-rider-d2@example.com", phone="9200000034", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add_all([admin, customer, owner, rider_a, rider_b])
    db.commit()
    # Rider Assignment Integration — reassign-rider now requires the
    # incoming rider to be an approved delivery partner.
    db.add(DeliveryPartner(user_id=rider_b.id, approval_status=ApprovalStatus.APPROVED))
    db.commit()

    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House D", phone="9876500002", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()

    order = Order(
        user_id=customer.id, rider_id=rider_a.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-P26-INTEGRITY-001", status="rider_assigned",
        subtotal=Decimal("100.00"), delivery_fee=Decimal("20.00"), total=Decimal("120.00"),
        payment_method="cod", address_line="1 Main St", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()

    db.add(Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID,
        amount=Decimal("155.00"), collected_by_rider_id=rider_a.id,
    ))
    db.commit()

    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    counts_before = {
        "users": _count(db, User), "orders": _count(db, Order), "restaurants": _count(db, Restaurant),
        "payments": _count(db, Payment),
    }

    reassign = client.post(
        f"/api/v1/admin/orders/{order.id}/reassign-rider",
        headers=headers, json={"new_rider_id": str(rider_b.id), "reason": "Rider D1 went offline"},
    )
    assert reassign.status_code == 200

    settle = client.post(f"/api/v1/admin/cod/{rider_a.id}/settle", headers=headers, json={"amount": "155.00"})
    assert settle.status_code == 200

    suspend = client.post(f"/api/v1/admin/customers/{customer.id}/suspend", headers=headers, json={"reason": "test"})
    assert suspend.status_code == 200

    counts_after = {
        "users": _count(db, User), "orders": _count(db, Order), "restaurants": _count(db, Restaurant),
        "payments": _count(db, Payment),
    }
    assert counts_after == counts_before

    # The only new rows created are the legitimate, documented ones: one
    # settlement (a ledger entry, not a copy of the order or the rider)
    # and audit-log entries (a log, not a copy of anything it describes).
    assert db.query(RiderSettlement).filter(RiderSettlement.rider_id == rider_a.id).count() == 1
    assert db.query(AdminAuditLog).count() == 3  # reassign, settle, suspend

    db.refresh(order)
    assert order.rider_id == rider_b.id  # the SAME order row, updated in place
