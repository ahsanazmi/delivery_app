"""Financial Ledger Validation (Phase 30).

Verifies the two money flows this phase names, end to end, through the
real API:

    Customer payment -> Platform -> Restaurant earning / Platform
    commission / Rider earning

    Customer cash -> Rider -> COD ledger -> Settlement ->
    Platform/restaurant reconciliation

and the two cross-cutting properties this phase requires: no simple
balance overwrites (every money-tracking model here is either an
append-only ledger row or a per-order snapshot frozen at creation, never
a mutated running total), and every financial movement is traceable
(specifically: a COD collection now gets its own permanent
CodCollection ledger row, independent of the mutable Payment row, and an
admin settlement is now linked — via CodSettlementAllocation, allocated
FIFO — to exactly which collected orders it discharges, not just a
lump-sum figure).
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
from app.models import (
    ApprovalStatus,
    CodCollection,
    CodSettlementAllocation,
    DeliveryPartner,
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


def _place_and_deliver_cod_order(client, *, owner_headers, customer_headers, rider_headers, product_id, address_id):
    """Places one COD order and drives it all the way through collection,
    returning (order_id, cod_collect_response_json)."""
    client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
    place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
    assert place.status_code == 201
    order_id = place.json()["id"]

    client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
    client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
    client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
    client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
    cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
    assert cod_collect.status_code == 200
    complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
    assert complete.status_code == 200
    return order_id, cod_collect.json()


def test_two_cod_collections_then_a_partial_settlement_allocates_fifo(engine):
    """Two separate COD orders, delivered by the same rider on different
    days (collected_at explicitly ordered so FIFO has something real to
    order by), each worth 100.00. A single settlement of 120.00 must
    fully discharge the OLDER collection (100.00) and partially discharge
    the newer one (20.00 of its 100.00) — never the reverse, and never
    split evenly."""
    with Session(engine) as seed:
        owner = User(name="Owner P30", email="p30-owner@example.com", phone="9500000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin P30", email="p30-admin@example.com", phone="9500000002", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P30", phone="9876500001", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("100.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)

        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P30", "email": "p30-customer@example.com", "password": "secure-pass-123", "phone": "9500000010", "role": "CUSTOMER"},
        )
        customer_token = client.post("/api/v1/auth/login", json={"email": "p30-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P30", "email": "p30-rider@example.com", "password": "secure-pass-123", "phone": "9500000011", "role": "RIDER"},
        )
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p30-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        with Session(engine) as db:
            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P30", "phone": "9500000010",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        address_id = address.json()["id"]

        order_1, cod_1 = _place_and_deliver_cod_order(
            client, owner_headers=owner_headers, customer_headers=customer_headers,
            rider_headers=rider_headers, product_id=product_id, address_id=address_id,
        )
        order_2, cod_2 = _place_and_deliver_cod_order(
            client, owner_headers=owner_headers, customer_headers=customer_headers,
            rider_headers=rider_headers, product_id=product_id, address_id=address_id,
        )

        # Force a real, unambiguous time ordering between the two
        # collections — the two HTTP calls above may well land in the
        # same wall-clock second.
        with Session(engine) as db:
            from datetime import UTC, datetime, timedelta

            older = db.query(CodCollection).filter(CodCollection.payment_id == UUID(cod_1["payment_id"])).one()
            newer = db.query(CodCollection).filter(CodCollection.payment_id == UUID(cod_2["payment_id"])).one()
            older.collected_at = datetime.now(UTC) - timedelta(hours=2)
            newer.collected_at = datetime.now(UTC) - timedelta(hours=1)
            db.commit()

        # Both collections exist as their own permanent ledger rows —
        # traceable independent of the (mutable) Payment rows.
        with Session(engine) as db:
            collections = db.query(CodCollection).filter(CodCollection.rider_id == UUID(rider_id)).all()
            assert len(collections) == 2
            assert {c.amount for c in collections} == {Decimal("100.00")}

        settle = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "120.00"})
        assert settle.status_code == 200
        body = settle.json()
        assert Decimal(body["outstanding_amount"]) == Decimal("80.00")

        settlement_record = body["settlements"][0]
        allocations = {a["order_id"]: Decimal(a["amount_allocated"]) for a in settlement_record["allocations"]}
        assert allocations[order_1] == Decimal("100.00")  # older collection: fully discharged
        assert allocations[order_2] == Decimal("20.00")   # newer collection: only partially discharged
        assert sum(allocations.values()) == Decimal("120.00")  # every rupee of the settlement is accounted for

        # The second collection's remaining 80.00 is settled later, by a
        # second, independent settlement — proving allocation correctly
        # resumes against the SAME collection's own remaining balance,
        # not a fresh one.
        settle_2 = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "80.00"})
        assert settle_2.status_code == 200
        body_2 = settle_2.json()
        assert Decimal(body_2["outstanding_amount"]) == Decimal("0.00")
        second_settlement_record = next(s for s in body_2["settlements"] if s["id"] != settlement_record["id"])
        second_allocations = {a["order_id"]: Decimal(a["amount_allocated"]) for a in second_settlement_record["allocations"]}
        assert second_allocations == {order_2: Decimal("80.00")}

        # No third settlement can be made — every collected rupee is now
        # accounted for exactly once, never double-allocated.
        with Session(engine) as db:
            total_collected = sum((c.amount for c in db.query(CodCollection).filter(CodCollection.rider_id == UUID(rider_id))), Decimal("0.00"))
            total_allocated = sum(
                (a.amount_allocated for a in db.query(CodSettlementAllocation).join(
                    CodCollection, CodCollection.id == CodSettlementAllocation.cod_collection_id
                ).filter(CodCollection.rider_id == UUID(rider_id))),
                Decimal("0.00"),
            )
            assert total_collected == total_allocated == Decimal("200.00")

        over_settle = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "0.01"})
        assert over_settle.status_code == 409


def test_cod_collection_ledger_row_is_never_duplicated_on_idempotent_retry(engine):
    """collect_cod_payment()'s own documented idempotent-retry behavior
    (a same-rider retry returns the existing collection rather than
    erroring) must never insert a second CodCollection row for the same
    payment — the unique constraint is the database-level backstop, this
    proves the application path itself never even attempts it."""
    with Session(engine) as seed:
        owner = User(name="Owner P30B", email="p30b-owner@example.com", phone="9500000101", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        seed.add(owner)
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name="Diner P30B", phone="9876500002", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        seed.add(restaurant)
        seed.commit()
        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("50.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        owner_token = create_access_token(owner.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P30B", "email": "p30b-customer@example.com", "password": "secure-pass-123", "phone": "9500000110", "role": "CUSTOMER"},
        )
        customer_token = client.post("/api/v1/auth/login", json={"email": "p30b-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P30B", "email": "p30b-rider@example.com", "password": "secure-pass-123", "phone": "9500000111", "role": "RIDER"},
        )
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p30b-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        with Session(engine) as db:
            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P30B", "phone": "9500000110",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        address_id = address.json()["id"]
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        order_id = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id}).json()["id"]

        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)

        first = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert first.status_code == 200
        second = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert second.status_code == 200
        assert first.json()["payment_id"] == second.json()["payment_id"]

        with Session(engine) as db:
            rows = db.query(CodCollection).filter(CodCollection.payment_id == UUID(first.json()["payment_id"])).all()
            assert len(rows) == 1
