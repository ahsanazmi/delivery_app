"""Payment System Phase 33 — COMPLETE COD E2E TEST.

Runs the exact flow this phase diagrams, through the real HTTP API
against a real database, and verifies every database record it
produces at every stage — not just the API's own JSON responses:

    Customer -> COD Checkout -> Order -> Restaurant -> Rider -> Delivery
    -> COD Collection -> Rider Ledger -> Settlement -> Admin Reconciliation

Every table this flow touches gets its own explicit assertion block,
directly against the database, immediately after the step that's
supposed to have written to it: orders, order_items,
order_status_history, delivery_assignments, payments, cod_collections
(Phase 30), rider_earnings, rider_settlements,
cod_settlement_allocations (Phase 30), admin_audit_logs — plus the
admin-facing reconciliation and reports endpoints, cross-checked against
those same rows.
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
    AdminAuditLog,
    ApprovalStatus,
    CodCollection,
    CodSettlementAllocation,
    CommissionRule,
    CommissionType,
    DeliveryAssignment,
    DeliveryPartner,
    Order,
    OrderItem,
    OrderStatus,
    OrderStatusHistory,
    Payment,
    PaymentProvider,
    PaymentStatus,
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


def test_complete_cod_flow_every_database_record_verified(engine):
    # ---- Seed: restaurant owner, admin, a 10% platform commission ----
    with Session(engine) as seed:
        owner = User(name="Owner P33", email="p33-owner@example.com", phone="9700000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin P33", email="p33-admin@example.com", phone="9700000002", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P33", phone="9876500000", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("40.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Thali", price=Decimal("260.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)
        restaurant_id = restaurant.id

        seed.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("10")))
        seed.commit()

        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P33", "email": "p33-customer@example.com", "password": "secure-pass-123", "phone": "9700000010", "role": "CUSTOMER"},
        )
        assert register_customer.status_code == 201
        customer_id = register_customer.json()["id"]
        customer_token = client.post("/api/v1/auth/login", json={"email": "p33-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P33", "email": "p33-rider@example.com", "password": "secure-pass-123", "phone": "9700000011", "role": "RIDER"},
        )
        assert register_rider.status_code == 201
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p33-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        with Session(engine) as db:
            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        # =====================================================================
        # STAGE 1 — Customer -> COD Checkout -> Order
        # =====================================================================
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P33", "phone": "9700000010",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        assert address.status_code == 201
        address_id = address.json()["id"]

        add_item = client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 2})
        assert add_item.status_code in (200, 201)

        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id})
        assert place.status_code == 201
        order_json = place.json()
        order_id = order_json["id"]
        assert order_json["payment_method"] == "cod"
        assert order_json["subtotal"] == "520.00"  # 2 x 260.00
        assert order_json["delivery_fee"] == "40.00"
        assert order_json["total"] == "560.00"

        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            assert db_order.status == OrderStatus.PLACED
            assert db_order.user_id == UUID(customer_id)
            assert db_order.payment_method == "cod"
            assert db_order.subtotal == Decimal("520.00")
            assert db_order.total == Decimal("560.00")
            # Commission snapshot, frozen at order-creation time (Phase 17/28).
            assert db_order.commission_type == "PERCENTAGE"
            assert db_order.commission_rate == Decimal("10")
            assert db_order.commission_amount == Decimal("52.00")  # 10% of 520.00 subtotal
            assert db_order.is_paid is False

            items = db.query(OrderItem).filter(OrderItem.order_id == UUID(order_id)).all()
            assert len(items) == 1
            assert items[0].product_id == product_id
            assert items[0].quantity == 2
            assert items[0].unit_price == Decimal("260.00")

            history = db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == UUID(order_id)).all()
            assert [h.status for h in history] == [OrderStatus.PLACED]

        # =====================================================================
        # STAGE 2 — Restaurant: accept -> preparing -> ready
        # =====================================================================
        accept = client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers)
        assert accept.status_code == 200
        assert accept.json()["status"] == "confirmed"

        preparing = client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers)
        assert preparing.status_code == 200
        assert preparing.json()["status"] == "preparing"

        ready = client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers)
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready_for_pickup"

        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            assert db_order.status == OrderStatus.READY_FOR_PICKUP
            history = db.query(OrderStatusHistory).filter(OrderStatusHistory.order_id == UUID(order_id)).order_by(OrderStatusHistory.created_at).all()
            assert [h.status for h in history] == [
                OrderStatus.PLACED, OrderStatus.CONFIRMED, OrderStatus.PREPARING, OrderStatus.READY_FOR_PICKUP,
            ]

        # =====================================================================
        # STAGE 3 — Rider: accept -> pickup -> start (out for delivery)
        # =====================================================================
        rider_accept = client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers)
        assert rider_accept.status_code == 200

        with Session(engine) as db:
            assignments = db.query(DeliveryAssignment).filter(DeliveryAssignment.order_id == UUID(order_id)).all()
            assert len(assignments) == 1
            assert assignments[0].rider_id == UUID(rider_id)
            db_order = db.get(Order, UUID(order_id))
            assert db_order.rider_id == UUID(rider_id)
            assert db_order.status == OrderStatus.RIDER_ASSIGNED

        pickup = client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers)
        assert pickup.status_code == 200
        start = client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers)
        assert start.status_code == 200

        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            assert db_order.status == OrderStatus.OUT_FOR_DELIVERY

        # =====================================================================
        # STAGE 4 — Delivery -> COD Collection
        # =====================================================================
        cod_collect = client.post(f"/api/v1/rider/deliveries/{order_id}/cod-collect", headers=rider_headers)
        assert cod_collect.status_code == 200
        cod_json = cod_collect.json()
        assert cod_json["amount"] == "560.00"
        assert cod_json["payment_status"] == "paid"
        payment_id = cod_json["payment_id"]

        with Session(engine) as db:
            payment = db.get(Payment, UUID(payment_id))
            assert payment.order_id == UUID(order_id)
            assert payment.provider == PaymentProvider.COD
            assert payment.payment_status == PaymentStatus.PAID
            assert payment.amount == Decimal("560.00")  # never overwritten by anything downstream
            assert payment.collected_by_rider_id == UUID(rider_id)
            assert payment.collected_at is not None

            db_order = db.get(Order, UUID(order_id))
            assert db_order.is_paid is True
            assert db_order.payment_status == "paid"

            # Financial Ledger Validation (Phase 30) — the collection's own
            # permanent, independent ledger row.
            collections = db.query(CodCollection).filter(CodCollection.payment_id == UUID(payment_id)).all()
            assert len(collections) == 1
            assert collections[0].amount == Decimal("560.00")
            assert collections[0].rider_id == UUID(rider_id)
            assert collections[0].order_id == UUID(order_id)

        # =====================================================================
        # STAGE 5 — Delivery completed -> Rider Ledger (RiderEarning)
        # =====================================================================
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["status"] == "delivered"

        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            assert db_order.status == OrderStatus.DELIVERED

            earnings = db.query(RiderEarning).filter(RiderEarning.rider_id == UUID(rider_id)).all()
            assert len(earnings) == 1
            assert earnings[0].amount == Decimal("40.00")  # exactly the order's own delivery_fee
            assert earnings[0].order_id == UUID(order_id)

        wallet = client.get("/api/v1/rider/wallet", headers=rider_headers)
        assert wallet.status_code == 200
        wallet_json = wallet.json()
        assert Decimal(wallet_json["total_earnings"]) == Decimal("40.00")
        assert Decimal(wallet_json["total_cod_collected"]) == Decimal("560.00")
        # wallet_balance = earnings - cod_collected - payouts + remittances:
        # the rider earned 40 in delivery fees but is holding 560 in cash
        # they don't own, so they owe the platform the net difference.
        assert Decimal(wallet_json["wallet_balance"]) == Decimal("40.00") - Decimal("560.00")
        assert Decimal(wallet_json["settlement_due"]) == Decimal(wallet_json["wallet_balance"])

        # =====================================================================
        # STAGE 6 — Settlement (admin settles part, then the rest)
        # =====================================================================
        settle_partial = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "300.00", "note": "First remittance"})
        assert settle_partial.status_code == 200
        assert settle_partial.json()["status"] == "PARTIAL"
        assert Decimal(settle_partial.json()["outstanding_amount"]) == Decimal("260.00")

        settle_rest = client.post(f"/api/v1/admin/cod/{rider_id}/settle", headers=admin_headers, json={"amount": "260.00", "note": "Final remittance"})
        assert settle_rest.status_code == 200
        assert settle_rest.json()["status"] == "SETTLED"
        assert Decimal(settle_rest.json()["outstanding_amount"]) == Decimal("0.00")

        with Session(engine) as db:
            settlements = db.query(RiderSettlement).filter(RiderSettlement.rider_id == UUID(rider_id)).order_by(RiderSettlement.created_at).all()
            assert len(settlements) == 2
            assert [s.amount for s in settlements] == [Decimal("300.00"), Decimal("260.00")]
            assert [s.note for s in settlements] == ["First remittance", "Final remittance"]

            # Financial Ledger Validation (Phase 30) — both settlements
            # together fully allocate against the one CodCollection, FIFO,
            # never double-counted.
            allocations = db.query(CodSettlementAllocation).join(
                CodCollection, CodCollection.id == CodSettlementAllocation.cod_collection_id
            ).filter(CodCollection.payment_id == UUID(payment_id)).all()
            assert len(allocations) == 2
            assert sum((a.amount_allocated for a in allocations), Decimal("0.00")) == Decimal("560.00")

            logs = db.query(AdminAuditLog).filter(
                AdminAuditLog.target_type == "rider", AdminAuditLog.target_id == rider_id, AdminAuditLog.action == "cod.settle",
            ).order_by(AdminAuditLog.created_at).all()
            assert len(logs) == 2
            assert logs[0].new_state == "260.00"  # outstanding after the first, partial settlement
            assert logs[1].new_state == "0.00"    # outstanding after the second, final settlement

        # =====================================================================
        # STAGE 7 — Admin Reconciliation
        # =====================================================================
        reconciliation = client.get(f"/api/v1/admin/cod/{rider_id}", headers=admin_headers)
        assert reconciliation.status_code == 200
        recon_json = reconciliation.json()
        assert recon_json["status"] == "SETTLED"
        assert Decimal(recon_json["cod_collected"]) == Decimal("560.00")
        assert Decimal(recon_json["settled_amount"]) == Decimal("560.00")
        assert Decimal(recon_json["outstanding_amount"]) == Decimal("0.00")
        assert len(recon_json["settlements"]) == 2
        for settlement_record in recon_json["settlements"]:
            assert sum(Decimal(a["amount_allocated"]) for a in settlement_record["allocations"]) == Decimal(settlement_record["amount"])

        overview = client.get("/api/v1/admin/reports/overview", headers=admin_headers).json()
        assert Decimal(overview["revenue"]) == Decimal("560.00")
        assert Decimal(overview["platform_commission"]) == Decimal("52.00")
        assert Decimal(overview["restaurant_earnings"]) == Decimal("468.00")  # 520 subtotal - 52 commission
        assert Decimal(overview["rider_earnings"]) == Decimal("40.00")
        assert Decimal(overview["cod_outstanding"]) == Decimal("0.00")
        # The reconciliation identity: every rupee of the customer's cash is
        # accounted for exactly once, split three ways, nothing left over.
        assert (
            Decimal(overview["restaurant_earnings"]) + Decimal(overview["platform_commission"]) + Decimal(overview["rider_earnings"])
        ) == Decimal("560.00") == Decimal(overview["revenue"])

        # Payment.amount, one final time — never overwritten by anything in
        # this entire eleven-step flow, from checkout through reconciliation.
        with Session(engine) as db:
            final_payment = db.get(Payment, UUID(payment_id))
            assert final_payment.amount == Decimal("560.00")
