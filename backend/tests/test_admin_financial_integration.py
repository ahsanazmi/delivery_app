"""Admin Portal — Phase 28: Admin Financial Integration Test.

Traces one real order all the way through the financial pipeline this
phase's brief diagrams:

    Customer order -> Payment -> Restaurant revenue -> Platform commission
    -> Rider earning -> COD collection -> Settlement -> Admin reports

and checks two cross-cutting properties: every money figure is a
Decimal/Numeric all the way through (never a float), and nothing is
double-counted.

This audit found one real bug, fixed as part of this phase (see
admin_reports.py's _order_financials): restaurant_earnings was computed as
`Order.total - commission_amount`, but Order.total includes delivery_fee —
money that belongs entirely to the rider (credited in full as its own
RiderEarning row), never to the restaurant. That formula silently counted
the delivery fee as earned income for both the restaurant and the rider at
once. It's now `Order.subtotal - commission_amount`, consistent with how
commission_amount itself was derived at order-creation time (on subtotal,
never on total — see services.commissions.compute_effective_commission).
The bug was invisible in Phase 19's own tests only because every order
there happened to have delivery_fee=0.00 (subtotal == total).
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
from app.models import (
    ApprovalStatus,
    CommissionRule,
    CommissionType,
    DeliveryPartner,
    Product,
    Restaurant,
    RiderEarning,
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


def test_full_financial_pipeline_no_double_counting_and_all_decimal(engine):
    """subtotal=200.00, delivery_fee=35.00 -> total=235.00, a 10% platform
    default commission -> commission_amount=20.00 (10% of subtotal, never
    of total). The whole point of using a nonzero delivery_fee here is
    that it's exactly the case Phase 19's own tests never exercised."""
    with Session(engine) as seed:
        owner = User(name="Owner P28", email="p28-owner@example.com", phone="9400000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin P28", email="p28-admin@example.com", phone="9400000002", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P28", phone="9876500000", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("35.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("200.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)

        # A 10% platform default commission — computed on subtotal only.
        seed.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10")))
        seed.commit()

        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P28", "email": "p28-customer@example.com", "password": "secure-pass-123", "phone": "9400000010", "role": "CUSTOMER"},
        )
        customer_token = client.post("/api/v1/auth/login", json={"email": "p28-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P28", "email": "p28-rider@example.com", "password": "secure-pass-123", "phone": "9400000011", "role": "RIDER"},
        )
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p28-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        with Session(engine) as db:
            from uuid import UUID

            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        # ---- CUSTOMER ORDER ----
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P28", "phone": "9400000010",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        address_id = address.json()["id"]
        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
        assert place.status_code == 201
        order = place.json()
        order_id = order["id"]

        # Decimal end to end: every money field arrives as a JSON string
        # (Decimal's serialization), never a JSON number (which is how a
        # float would come through).
        for field in ("subtotal", "delivery_fee", "tax", "discount", "total"):
            assert isinstance(order[field], str), (field, order[field])
        assert order["subtotal"] == "200.00"
        assert order["delivery_fee"] == "35.00"
        assert order["total"] == "235.00"

        # ---- COMMISSION snapshot, taken on subtotal, at order-creation time ----
        admin_order = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_order.status_code == 200

        with Session(engine) as db:
            from app.models.order import Order as OrderModel

            db_order = db.get(OrderModel, UUID(order_id))
            assert db_order.commission_type == "PERCENTAGE"
            assert db_order.commission_rate == Decimal("10")
            assert db_order.commission_amount == Decimal("20.00")  # 10% of 200.00 subtotal, not of 235.00 total

        # ---- RESTAURANT progresses; RIDER delivers, collecting COD ----
        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)

        cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert cod_collect.status_code == 200
        payment_id = cod_collect.json()["payment_id"]
        # The RIDER collects the FULL order total in cash — this is a
        # completely different figure from what the rider actually earns
        # (the delivery fee alone, credited separately below). Conflating
        # these two would be its own double-counting bug (see rider_wallet's
        # own "COD debt and earnings are always two separate ledgers" rule).
        assert isinstance(cod_collect.json()["amount"], str)
        assert Decimal(cod_collect.json()["amount"]) == Decimal("235.00")

        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200

        # ---- PAYMENT, as admin sees it ----
        admin_payment = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers)
        assert admin_payment.status_code == 200
        assert isinstance(admin_payment.json()["amount"], str)
        assert Decimal(admin_payment.json()["amount"]) == Decimal("235.00")
        assert admin_payment.json()["status"] == "PAID"

        # ---- RIDER EARNING: exactly the restaurant's own delivery_fee ----
        with Session(engine) as db:
            earnings = db.query(RiderEarning).filter(RiderEarning.rider_id == UUID(rider_id)).all()
            assert len(earnings) == 1
            assert earnings[0].amount == Decimal("35.00")
            assert earnings[0].order_id == UUID(order_id)

        # ---- SETTLEMENT: rider remits the COD cash they physically hold ----
        settle = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "235.00"})
        assert settle.status_code == 200
        assert isinstance(settle.json()["outstanding_amount"], str)
        assert Decimal(settle.json()["outstanding_amount"]) == Decimal("0.00")

        with Session(engine) as db:
            settlements = db.query(RiderSettlement).filter(RiderSettlement.rider_id == UUID(rider_id)).all()
            assert len(settlements) == 1
            assert settlements[0].amount == Decimal("235.00")

        # ---- ADMIN REPORTS: the reconciliation that must not double-count ----
        overview = client.get("/api/v1/admin/reports/overview", headers=admin_headers).json()
        for field in ("revenue", "platform_commission", "restaurant_earnings", "rider_earnings", "cod_outstanding"):
            assert isinstance(overview[field], str), field

        assert Decimal(overview["revenue"]) == Decimal("235.00")           # gross, customer-paid total
        assert Decimal(overview["platform_commission"]) == Decimal("20.00")  # 10% of subtotal
        # The core assertion this whole phase is about: restaurant_earnings
        # must be the subtotal-based figure (100.00 minus... 200.00 - 20.00
        # = 180.00), never the total-based one (235.00 - 20.00 = 215.00,
        # which would double-count the 35.00 delivery fee the rider already
        # earned separately).
        assert Decimal(overview["restaurant_earnings"]) == Decimal("180.00")
        assert Decimal(overview["rider_earnings"]) == Decimal("35.00")
        assert Decimal(overview["cod_outstanding"]) == Decimal("0.00")

        # Reconciliation identity: every rupee of the customer's payment is
        # accounted for exactly once, split three ways, with nothing left
        # over and nothing counted twice.
        assert (
            Decimal(overview["restaurant_earnings"])
            + Decimal(overview["platform_commission"])
            + Decimal(overview["rider_earnings"])
        ) == Decimal("235.00") == Decimal(overview["revenue"])

        revenue_report = client.get("/api/v1/admin/reports/revenue", headers=admin_headers).json()
        assert Decimal(revenue_report["restaurant_earnings"]) == Decimal("180.00")
        assert Decimal(revenue_report["platform_commission"]) == Decimal("20.00")


# --------------------------------------------------------------------
# Double-counting regression checks
# --------------------------------------------------------------------


def test_retrying_cod_collect_never_creates_a_second_payment_or_charges_twice(client):
    """Idempotent retry (Phase 28's own note in rider_deliveries.py) — a
    lost-response retry of cod-collect must return the same payment, not
    create a second one or double the collected amount."""
    db = next(client.app.dependency_overrides[get_db]())
    from decimal import Decimal as D
    from uuid import uuid4

    from app.models.order import Order, OrderStatus
    from app.models.payment import Payment

    owner = User(name="Owner P28b", email="p28b-owner@example.com", phone="9400000020", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer P28b", email="p28b-customer@example.com", phone="9400000021", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    rider = User(name="Rider P28b", email="p28b-rider@example.com", phone="9400000022", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add_all([owner, customer, rider])
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House P28b", phone="9876500001", address="Addr",
        latitude=D("12.97"), longitude=D("77.59"), minimum_order=D("0.00"), delivery_fee=D("20.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, rider_id=rider.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{uuid4().hex[:20]}", status=OrderStatus.OUT_FOR_DELIVERY,
        subtotal=D("80.00"), delivery_fee=D("20.00"), total=D("100.00"),
        payment_method="cod", address_line="1 Main St", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()

    rider_headers = {"Authorization": f"Bearer {create_access_token(rider.id)}"}

    first = client.post(f"/api/v1/rider/deliveries/{order.id}/cod-collect", headers=rider_headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/rider/deliveries/{order.id}/cod-collect", headers=rider_headers)
    assert second.status_code == 200
    assert first.json()["payment_id"] == second.json()["payment_id"]

    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1
    payment = db.query(Payment).filter(Payment.order_id == order.id).one()
    assert payment.amount == D("100.00")


def test_retrying_delivery_completion_never_credits_rider_earning_twice(client):
    db = next(client.app.dependency_overrides[get_db]())
    from decimal import Decimal as D
    from uuid import uuid4

    from app.models.order import Order, OrderStatus
    from app.models.payment import Payment, PaymentProvider, PaymentStatus

    owner = User(name="Owner P28c", email="p28c-owner@example.com", phone="9400000030", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer P28c", email="p28c-customer@example.com", phone="9400000031", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    rider = User(name="Rider P28c", email="p28c-rider@example.com", phone="9400000032", password_hash=hash_password("x"), role=UserRole.RIDER)
    db.add_all([owner, customer, rider])
    db.commit()
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House P28c", phone="9876500002", address="Addr",
        latitude=D("12.97"), longitude=D("77.59"), minimum_order=D("0.00"), delivery_fee=D("25.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, rider_id=rider.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{uuid4().hex[:20]}", status=OrderStatus.OUT_FOR_DELIVERY,
        subtotal=D("75.00"), delivery_fee=D("25.00"), total=D("100.00"), is_paid=True,
        payment_method="cod", address_line="1 Main St", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.add(Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID, amount=D("100.00"), collected_by_rider_id=rider.id))
    db.commit()

    rider_headers = {"Authorization": f"Bearer {create_access_token(rider.id)}"}

    first = client.post(f"/api/v1/rider/deliveries/{order.id}/complete", headers=rider_headers)
    assert first.status_code == 200
    second = client.post(f"/api/v1/rider/deliveries/{order.id}/complete", headers=rider_headers)
    assert second.status_code == 200

    assert db.query(RiderEarning).filter(RiderEarning.order_id == order.id).count() == 1


def test_changing_commission_rule_never_alters_a_historical_orders_contribution_to_reports(client):
    """Phase 17's own guarantee, re-verified here specifically through the
    Admin Reports surface this phase's pipeline ends at — the whole point
    of a snapshot is that changing today's rule can never quietly rewrite
    yesterday's numbers."""
    db = next(client.app.dependency_overrides[get_db]())
    from decimal import Decimal as D
    from uuid import uuid4

    from app.models.order import Order, OrderStatus

    owner = User(name="Owner P28d", email="p28d-owner@example.com", phone="9400000040", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer P28d", email="p28d-customer@example.com", phone="9400000041", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    admin = User(name="Admin P28d", email="p28d-admin@example.com", phone="9400000042", password_hash=hash_password("x"), role=UserRole.ADMIN)
    db.add_all([owner, customer, admin])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="Chai House P28d", phone="9876500003", address="Addr",
        latitude=D("12.97"), longitude=D("77.59"), minimum_order=D("0.00"), delivery_fee=D("30.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{uuid4().hex[:20]}", status=OrderStatus.DELIVERED,
        subtotal=D("100.00"), delivery_fee=D("30.00"), total=D("130.00"),
        commission_type="PERCENTAGE", commission_rate=D("10"), commission_amount=D("10.00"),
        payment_method="cod", address_line="1 Main St", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()

    admin_headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    before = client.get("/api/v1/admin/reports/overview", headers=admin_headers).json()
    assert Decimal(before["platform_commission"]) == Decimal("10.00")
    assert Decimal(before["restaurant_earnings"]) == Decimal("90.00")

    update = client.patch(
        "/api/v1/admin/commissions", headers=admin_headers,
        json={"default": {"commission_type": "FIXED", "value": "999.00"}},
    )
    assert update.status_code == 200

    after = client.get("/api/v1/admin/reports/overview", headers=admin_headers).json()
    assert Decimal(after["platform_commission"]) == Decimal("10.00")
    assert Decimal(after["restaurant_earnings"]) == Decimal("90.00")
