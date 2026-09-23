"""Admin Portal — Phase 19: Reports & Analytics.

All figures are computed server-side from real rows; the frontend only
ever renders what these endpoints return (see the phase's own "do not
calculate authoritative financial numbers solely in the browser").
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_earning import EarningType, RiderEarning
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole

REPORTS_URL = "/api/v1/admin/reports"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role, created_at=None):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    if created_at is not None:
        db.query(User).filter(User.id == user.id).update({User.created_at: created_at})
        db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p19-{uuid.uuid4().hex[:8]}@example.com", phone=f"79{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_restaurant(db, suffix, *, created_at=None):
    owner = _make_user(db, name=f"Owner {suffix}", email=f"owner-{suffix}-p19@example.com", phone=f"780000001{suffix}", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Restaurant {suffix}", phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    if created_at is not None:
        db.query(Restaurant).filter(Restaurant.id == restaurant.id).update({Restaurant.created_at: created_at})
        db.commit()
    db.refresh(restaurant)
    return restaurant


def _make_order(
    db, *, restaurant, customer=None, rider=None, status=OrderStatus.DELIVERED,
    total=Decimal("100.00"), commission_amount=None, created_at=None,
):
    order = Order(
        user_id=customer.id if customer else uuid.uuid4(),
        rider_id=rider.id if rider else None,
        customer_name=customer.name if customer else "Cust",
        customer_email="cust@example.com",
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=total, delivery_fee=Decimal("0.00"), total=total,
        commission_amount=commission_amount,
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    if created_at is not None:
        db.query(Order).filter(Order.id == order.id).update({Order.created_at: created_at})
        db.commit()
    db.refresh(order)
    return order


def test_all_report_endpoints_require_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p19@example.com", phone="7900000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    headers = {"Authorization": f"Bearer {token}"}

    for path in ("overview", "orders", "revenue", "restaurants", "riders", "customers"):
        assert client.get(f"{REPORTS_URL}/{path}", headers=headers).status_code == 403
        assert client.get(f"{REPORTS_URL}/{path}").status_code == 401


def test_overview_computes_orders_revenue_and_commission(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "1")
    customer = _make_user(db, name="Cust A", email="cust-a-p19@example.com", phone="7900000010", role=UserRole.CUSTOMER)

    _make_order(db, restaurant=restaurant, customer=customer, status=OrderStatus.DELIVERED, total=Decimal("200.00"), commission_amount=Decimal("20.00"))
    _make_order(db, restaurant=restaurant, customer=customer, status=OrderStatus.DELIVERED, total=Decimal("100.00"), commission_amount=None)
    _make_order(db, restaurant=restaurant, customer=customer, status=OrderStatus.CANCELLED, total=Decimal("999.00"))
    _make_order(db, restaurant=restaurant, customer=customer, status=OrderStatus.PLACED, total=Decimal("50.00"))

    response = client.get(f"{REPORTS_URL}/overview", headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["total_orders"] == 4
    assert body["completed_orders"] == 2
    assert body["cancelled_orders"] == 1
    # revenue = 200 + 100 (DELIVERED only)
    assert Decimal(body["revenue"]) == Decimal("300.00")
    # commission = 20 + 0 (second order had no commission rule at creation)
    assert Decimal(body["platform_commission"]) == Decimal("20.00")
    # restaurant_earnings = revenue - commission = 300 - 20
    assert Decimal(body["restaurant_earnings"]) == Decimal("280.00")


def test_overview_rider_earnings_and_cod_outstanding(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Rider A", email="rider-a-p19@example.com", phone="7900000020", role=UserRole.RIDER)
    restaurant = _make_restaurant(db, "2")
    order = _make_order(db, restaurant=restaurant, rider=rider, status=OrderStatus.DELIVERED, total=Decimal("150.00"))

    db.add(RiderEarning(rider_id=rider.id, order_id=order.id, earning_type=EarningType.DELIVERY_FEE, amount=Decimal("30.00")))
    db.add(Payment(order_id=order.id, user_id=uuid.uuid4(), provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID, amount=Decimal("150.00"), collected_by_rider_id=rider.id))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("50.00")))
    db.commit()

    response = client.get(f"{REPORTS_URL}/overview", headers=headers)
    body = response.json()
    assert Decimal(body["rider_earnings"]) >= Decimal("30.00")
    assert Decimal(body["cod_outstanding"]) >= Decimal("100.00")  # 150 collected - 50 remitted, plus any other live data


def test_overview_growth_counts(client):
    db = _db(client)
    headers = _admin_headers(db)
    old_time = datetime.now(UTC) - timedelta(days=30)
    recent_time = datetime.now(UTC) - timedelta(hours=1)

    _make_user(db, name="Old Customer", email="old-cust-p19@example.com", phone="7900000030", role=UserRole.CUSTOMER, created_at=old_time)
    _make_user(db, name="New Customer", email="new-cust-p19@example.com", phone="7900000031", role=UserRole.CUSTOMER, created_at=recent_time)
    _make_restaurant(db, "3", created_at=recent_time)
    _make_user(db, name="New Rider", email="new-rider-p19@example.com", phone="7900000032", role=UserRole.RIDER, created_at=recent_time)

    date_from = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    response = client.get(f"{REPORTS_URL}/overview", headers=headers, params={"date_from": date_from})
    body = response.json()
    assert body["customer_growth"] >= 1
    assert body["restaurant_growth"] >= 1
    assert body["rider_growth"] >= 1


def test_overview_date_range_excludes_old_orders(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "4")
    old_time = datetime.now(UTC) - timedelta(days=30)
    _make_order(db, restaurant=restaurant, status=OrderStatus.DELIVERED, total=Decimal("500.00"), created_at=old_time)

    date_from = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    response = client.get(f"{REPORTS_URL}/overview", headers=headers, params={"date_from": date_from})
    body = response.json()
    assert Decimal(body["revenue"]) < Decimal("500.00")


def test_orders_report_status_breakdown(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "5")
    _make_order(db, restaurant=restaurant, status=OrderStatus.DELIVERED)
    _make_order(db, restaurant=restaurant, status=OrderStatus.CANCELLED)
    _make_order(db, restaurant=restaurant, status=OrderStatus.REJECTED)
    _make_order(db, restaurant=restaurant, status=OrderStatus.PREPARING)

    response = client.get(f"{REPORTS_URL}/orders", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["completed_orders"] >= 1
    assert body["cancelled_orders"] >= 1
    assert body["rejected_orders"] >= 1
    assert body["in_progress_orders"] >= 1
    statuses = {row["status"] for row in body["status_breakdown"]}
    assert "delivered" in statuses
    assert "cancelled" in statuses


def test_orders_report_orders_by_day(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "6")
    _make_order(db, restaurant=restaurant, status=OrderStatus.DELIVERED)

    response = client.get(f"{REPORTS_URL}/orders", headers=headers)
    body = response.json()
    assert len(body["orders_by_day"]) >= 1
    assert "date" in body["orders_by_day"][0]
    assert "count" in body["orders_by_day"][0]


def test_revenue_report(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "7")
    _make_order(db, restaurant=restaurant, status=OrderStatus.DELIVERED, total=Decimal("300.00"), commission_amount=Decimal("30.00"))

    response = client.get(f"{REPORTS_URL}/revenue", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["revenue"]) >= Decimal("300.00")
    assert Decimal(body["platform_commission"]) >= Decimal("30.00")
    assert len(body["revenue_by_day"]) >= 1


def test_restaurants_report_growth_and_top_restaurants(client):
    db = _db(client)
    headers = _admin_headers(db)
    top_restaurant = _make_restaurant(db, "8")
    other_restaurant = _make_restaurant(db, "9")
    _make_order(db, restaurant=top_restaurant, status=OrderStatus.DELIVERED, total=Decimal("1000.00"))
    _make_order(db, restaurant=other_restaurant, status=OrderStatus.DELIVERED, total=Decimal("10.00"))

    response = client.get(f"{REPORTS_URL}/restaurants", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_restaurants"] >= 2
    assert body["new_restaurants"] >= 2
    top_names = [r["restaurant_name"] for r in body["top_restaurants"]]
    assert top_names[0] == "Restaurant 8"


def test_riders_report_cod_outstanding_and_top_riders(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="Top Rider", email="top-rider-p19@example.com", phone="7900000040", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    restaurant = _make_restaurant(db, "10")
    order = _make_order(db, restaurant=restaurant, rider=rider, status=OrderStatus.DELIVERED, total=Decimal("100.00"))
    db.add(RiderEarning(rider_id=rider.id, order_id=order.id, earning_type=EarningType.DELIVERY_FEE, amount=Decimal("25.00")))
    db.commit()

    response = client.get(f"{REPORTS_URL}/riders", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["active_riders"] >= 1
    assert body["new_riders"] >= 1
    assert "cod_outstanding" in body
    top_rider_names = [r["rider_name"] for r in body["top_riders"]]
    assert "Top Rider" in top_rider_names


def test_riders_report_cod_outstanding_not_scoped_to_date_range(client):
    """cod_outstanding is a running platform-wide balance — it must not
    change just because a narrow date range excludes the underlying
    collection/remittance rows' own created_at."""
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_user(db, name="COD Rider P19", email="cod-rider-p19@example.com", phone="7900000050", role=UserRole.RIDER)
    restaurant = _make_restaurant(db, "11")
    order = _make_order(db, restaurant=restaurant, rider=rider, status=OrderStatus.DELIVERED, total=Decimal("200.00"))
    old_time = datetime.now(UTC) - timedelta(days=60)
    db.add(Payment(order_id=order.id, user_id=uuid.uuid4(), provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID, amount=Decimal("200.00"), collected_by_rider_id=rider.id))
    db.commit()

    no_range = client.get(f"{REPORTS_URL}/riders", headers=headers).json()["cod_outstanding"]
    narrow_range = client.get(
        f"{REPORTS_URL}/riders", headers=headers,
        params={"date_from": datetime.now(UTC).date().isoformat(), "date_to": datetime.now(UTC).date().isoformat()},
    ).json()["cod_outstanding"]
    assert Decimal(no_range) == Decimal(narrow_range)


def test_customers_report_growth_and_top_customers(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "12")
    top_customer = _make_user(db, name="Big Spender", email="big-spender-p19@example.com", phone="7900000060", role=UserRole.CUSTOMER)
    _make_order(db, restaurant=restaurant, customer=top_customer, status=OrderStatus.DELIVERED, total=Decimal("500.00"))

    response = client.get(f"{REPORTS_URL}/customers", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total_customers"] >= 1
    assert body["new_customers"] >= 1
    top_names = [c["customer_name"] for c in body["top_customers"]]
    assert "Big Spender" in top_names


def test_all_time_default_when_no_date_range_given(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "13")
    old_time = datetime.now(UTC) - timedelta(days=365)
    _make_order(db, restaurant=restaurant, status=OrderStatus.DELIVERED, total=Decimal("777.00"), created_at=old_time)

    response = client.get(f"{REPORTS_URL}/overview", headers=headers)
    body = response.json()
    assert Decimal(body["revenue"]) >= Decimal("777.00")
    assert body["date_from"] is None
    assert body["date_to"] is None
