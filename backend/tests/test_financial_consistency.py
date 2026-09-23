"""Integration Phase 23 — Financial Consistency Test.

Walks one real, fully-realistic sample order (a coupon discount applied,
COD collected, a commission rule in effect) through the entire money
chain and proves every figure this phase names — customer total, customer
payment, restaurant earning, platform commission, rider earning, COD
amount — agrees with the others, uses Decimal/NUMERIC throughout, and
never goes negative unexpectedly.

Sample order:
    2 x Masala Dosa @ 100.00       subtotal    = 200.00
    delivery fee                               =  30.00
    tax (no tax policy exists yet, see
      calculate_cart_totals's own note)         =   0.00
    10% coupon on subtotal (SAVE10)  discount  =  20.00
    -------------------------------------------------
    customer total = 200 + 30 + 0 - 20         = 210.00

    commission (10% platform rate, on the GROSS
    subtotal — never on the discounted amount,
    see compute_effective_commission's own note) =  20.00
    restaurant earning = subtotal - commission   = 180.00
    rider earning = delivery_fee (unaffected
      by the discount — the rider's payout was
      never based on subtotal at all)            =  30.00

Note on why restaurant_earning + commission (200) can exceed what a COD
rider actually remits after keeping their own cut (210 - 30 = 180): the
discount is a platform-funded promotion, the same model real delivery
platforms use — the restaurant and rider are both paid in full regardless
of a coupon; the platform absorbs the 20.00 gap itself. This is
intentional (see admin_reports.py's own extensive comment on why
restaurant_earnings is deliberately subtotal - commission, never derived
from total) and does not constitute double-counting: COD reconciliation
(rider_deliveries.collect_cod_payment / admin_cod.py) and the revenue
report (admin_reports.py) are two independent ledgers measuring different
things — cash physically collected vs. booked commission/earnings — and
are never added together anywhere in this codebase.
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
from app.models.commission_rule import CommissionRule, CommissionType
from app.models.coupon import Coupon, DiscountType
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.payment import Payment
from app.models.rider_earning import RiderEarning
from app.services.addresses import create_address
from app.services.admin_reports import _order_financials


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


def test_sample_order_financial_chain_is_fully_consistent(engine):
    with Session(engine) as seed:
        owner = User(name="Owner", email="owner-p23@example.com", phone="9700000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Customer", email="customer-p23@example.com", phone="9700000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        rider = User(name="Rider", email="rider-p23@example.com", phone="9700000003", password_hash=hash_password("x"), role=UserRole.RIDER)
        admin = User(name="Admin", email="admin-p23@example.com", phone="9700000004", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, customer, rider, admin])
        seed.commit()
        seed.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True))

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House", phone="9876543210", address="Main Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()

        # 10% platform commission, on subtotal.
        seed.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10.00")))
        # SAVE10: 10% off subtotal, no cap.
        seed.add(Coupon(
            code="SAVE10", discount_type=DiscountType.PERCENT, discount_value=Decimal("10.00"),
            min_order=Decimal("0.00"), is_active=True,
        ))
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("100.00"))
        seed.add(product)
        seed.commit()
        product_id = product.id

        address = create_address(seed, customer.id, {
            "label": "Home", "recipient_name": "Customer", "phone": "9700000002",
            "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "123456",
        })
        address_id = address.id

        owner_token = create_access_token(owner.id)
        customer_token = create_access_token(customer.id)
        rider_token = create_access_token(rider.id)
        admin_token = create_access_token(admin.id)

    owner_headers = {"Authorization": f"Bearer {owner_token}"}
    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    rider_headers = {"Authorization": f"Bearer {rider_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    with TestClient(app) as client:
        add_item = client.post(
            "/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": str(product_id), "quantity": 2}
        )
        assert add_item.status_code == 201

        applied = client.post("/api/v1/customer/cart/apply-coupon", headers=customer_headers, json={"code": "SAVE10"})
        assert applied.status_code == 200
        cart = applied.json()

        # ---- Step 1: Item subtotal + Tax + Delivery fee - Discount = Customer total ----
        assert cart["subtotal"] == "200.00"
        assert cart["tax"] == "0.00"
        assert cart["delivery_fee"] == "30.00"
        assert cart["discount"] == "20.00"
        assert cart["total"] == "210.00"
        assert Decimal(cart["subtotal"]) + Decimal(cart["tax"]) + Decimal(cart["delivery_fee"]) - Decimal(cart["discount"]) == Decimal(cart["total"])

        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": str(address_id)})
        assert place.status_code == 201
        order = place.json()
        order_id = order["id"]

        # The placed order's own stored fields match the checkout preview exactly.
        assert order["subtotal"] == "200.00"
        assert order["delivery_fee"] == "30.00"
        assert order["tax"] == "0.00"
        assert order["discount"] == "20.00"
        assert order["total"] == "210.00"
        assert order["payment_method"] == "cod"

        # ---- Step 2: Platform commission, snapshotted at order-creation time ----
        db_gen = client.app.dependency_overrides[get_db]()
        db = next(db_gen)
        from uuid import UUID
        from app.models.order import Order

        order_row = db.query(Order).filter(Order.id == UUID(order_id)).one()
        assert order_row.commission_type == "PERCENTAGE"
        assert order_row.commission_rate == Decimal("10.00")
        # Computed on the GROSS subtotal (200), never the discounted amount.
        assert order_row.commission_amount == Decimal("20.00")
        db.close()

        # Drive the order to delivered + COD collected.
        client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)

        # ---- Step 3: COD amount == customer payment == customer total, exactly ----
        collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert collect.status_code == 200
        assert collect.json()["amount"] == "210.00"

        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["payment_status"] == "paid"
        assert complete.json()["is_paid"] is True

        # ---- Step 4: No mismatch between order and payment ----
        db_gen2 = client.app.dependency_overrides[get_db]()
        db2 = next(db_gen2)
        payment = db2.query(Payment).filter(Payment.order_id == UUID(order_id)).one()
        assert payment.amount == Decimal("210.00")
        assert payment.amount == order_row.total  # order and payment agree, to the cent

        # ---- Step 5: Rider earning ----
        earning = db2.query(RiderEarning).filter(RiderEarning.order_id == UUID(order_id)).one()
        assert earning.amount == Decimal("30.00")  # exactly delivery_fee, never subtotal or total
        db2.close()

        # ---- Step 6: Restaurant earning + platform commission, via the admin report ----
        db_gen3 = client.app.dependency_overrides[get_db]()
        db3 = next(db_gen3)
        revenue, commission, restaurant_earnings = _order_financials(db3, None, None)
        assert commission == Decimal("20.00")
        assert restaurant_earnings == Decimal("180.00")  # subtotal (200) - commission (20)
        # No double counting: restaurant_earnings + commission always equals
        # the full subtotal, independent of any discount applied — the
        # discount is absorbed by the platform, not by netting it out of
        # either the restaurant's or the rider's share.
        assert restaurant_earnings + commission == order_row.subtotal
        db3.close()

        # ---- Step 7: No negative unexpected values anywhere in the chain ----
        for value in (order["subtotal"], order["delivery_fee"], order["tax"], order["discount"], order["total"]):
            assert Decimal(value) >= 0
        assert commission >= 0
        assert restaurant_earnings >= 0
        assert earning.amount >= 0
        assert payment.amount >= 0

        # ---- Step 8: Decimal/NUMERIC throughout — never float ----
        assert isinstance(order_row.subtotal, Decimal)
        assert isinstance(order_row.total, Decimal)
        assert isinstance(order_row.commission_amount, Decimal)
        assert isinstance(payment.amount, Decimal)
        assert isinstance(earning.amount, Decimal)

        # ---- Admin sees the same order total via the API too ----
        admin_view = client.get(f"/api/v1/admin/orders/{order_id}", headers=admin_headers)
        assert admin_view.json()["total"] == "210.00"
        assert admin_view.json()["subtotal"] == "200.00"
        assert admin_view.json()["discount"] == "20.00"
