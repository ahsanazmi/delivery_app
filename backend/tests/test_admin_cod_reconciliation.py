"""Admin Portal — Phase 14: COD Reconciliation.

RiderSettlement's own docstring says "there is no endpoint here that
writes one yet" — POST /admin/cod/{rider_id}/settle is that first write
path, and it must always INSERT a new ledger row, never overwrite a
balance (there is no balance column to overwrite — every figure is
derived fresh from Payment + RiderSettlement on every request).
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.cod_collection import CodCollection
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole

COD_URL = "/api/v1/admin/cod"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p14-{uuid.uuid4().hex[:8]}@example.com", phone=f"83{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_rider(db, suffix):
    return _make_user(db, name=f"COD Rider {suffix}", email=f"cod-rider-{suffix}-p14@example.com", phone=f"82000000{suffix}", role=UserRole.RIDER)


def _make_cod_collection(db, *, rider, amount):
    order = Order(
        user_id=uuid.uuid4(), rider_id=rider.id, customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.DELIVERED,
        subtotal=amount, delivery_fee=Decimal("0.00"), total=amount,
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    from datetime import UTC, datetime

    collected_at = datetime.now(UTC)
    payment = Payment(
        order_id=order.id, user_id=uuid.uuid4(), provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID,
        amount=amount, collected_by_rider_id=rider.id, collected_at=collected_at,
    )
    db.add(payment)
    db.commit()
    # Financial Ledger Validation (Phase 30) — collect_cod_payment() now
    # always writes this row alongside the Payment mutation above; mirrored
    # here so this test fixture's data matches what a real collection
    # actually produces (admin_settle_cod()'s FIFO allocation reads from
    # this table, not from Payment directly).
    db.add(CodCollection(payment_id=payment.id, order_id=order.id, rider_id=rider.id, amount=amount, collected_at=collected_at))
    db.commit()
    return payment


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p14@example.com", phone="8200000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(COD_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(COD_URL).status_code == 401


def test_list_shows_rider_with_pending_status(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "10")
    _make_cod_collection(db, rider=rider, amount=Decimal("500.00"))

    response = client.get(COD_URL, headers=headers)
    assert response.status_code == 200
    match = next(item for item in response.json()["items"] if item["rider_id"] == str(rider.id))
    assert Decimal(match["cod_collected"]) == Decimal("500.00")
    assert Decimal(match["expected_settlement"]) == Decimal("500.00")
    assert Decimal(match["settled_amount"]) == Decimal("0.00")
    assert Decimal(match["outstanding_amount"]) == Decimal("500.00")
    assert match["status"] == "PENDING"


def test_list_excludes_riders_with_no_cod_activity(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    _make_rider(db, "20")  # never collected anything

    response = client.get(COD_URL, headers=headers)
    names = [item["rider_name"] for item in response.json()["items"]]
    assert "COD Rider 20" not in names


def test_list_partial_status_after_partial_settlement(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "30")
    _make_cod_collection(db, rider=rider, amount=Decimal("1000.00"))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("400.00")))
    db.commit()

    response = client.get(COD_URL, headers=headers)
    match = next(item for item in response.json()["items"] if item["rider_id"] == str(rider.id))
    assert Decimal(match["settled_amount"]) == Decimal("400.00")
    assert Decimal(match["outstanding_amount"]) == Decimal("600.00")
    assert match["status"] == "PARTIAL"


def test_list_settled_status_when_fully_remitted(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "40")
    _make_cod_collection(db, rider=rider, amount=Decimal("300.00"))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("300.00")))
    db.commit()

    response = client.get(COD_URL, headers=headers)
    match = next(item for item in response.json()["items"] if item["rider_id"] == str(rider.id))
    assert Decimal(match["outstanding_amount"]) == Decimal("0.00")
    assert match["status"] == "SETTLED"


def test_status_filter(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    pending_rider = _make_rider(db, "50")
    _make_cod_collection(db, rider=pending_rider, amount=Decimal("200.00"))
    settled_rider = _make_rider(db, "51")
    _make_cod_collection(db, rider=settled_rider, amount=Decimal("200.00"))
    db.add(RiderSettlement(rider_id=settled_rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("200.00")))
    db.commit()

    response = client.get(COD_URL, headers=headers, params={"status": "PENDING"})
    rider_ids = [item["rider_id"] for item in response.json()["items"]]
    assert str(pending_rider.id) in rider_ids
    assert str(settled_rider.id) not in rider_ids


def test_search_by_rider_name(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    findable = _make_rider(db, "60")
    findable.name = "Findable COD Rider"
    db.commit()
    _make_cod_collection(db, rider=findable, amount=Decimal("100.00"))
    other = _make_rider(db, "61")
    _make_cod_collection(db, rider=other, amount=Decimal("100.00"))

    response = client.get(COD_URL, headers=headers, params={"search": "Findable"})
    names = [item["rider_name"] for item in response.json()["items"]]
    assert names == ["Findable COD Rider"]


def test_detail_includes_settlement_history(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "70")
    _make_cod_collection(db, rider=rider, amount=Decimal("500.00"))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("200.00"), note="First remittance"))
    db.commit()

    response = client.get(f"{COD_URL}/{rider.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["settlements"]) == 1
    assert body["settlements"][0]["amount"] == "200.00"
    assert body["settlements"][0]["note"] == "First remittance"


def test_detail_excludes_payout_settlements(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "80")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.PAYOUT, amount=Decimal("999.00"), note="Unrelated earnings payout"))
    db.commit()

    response = client.get(f"{COD_URL}/{rider.id}", headers=headers)
    body = response.json()
    assert body["settlements"] == []
    assert Decimal(body["settled_amount"]) == Decimal("0.00")


def test_detail_404_for_missing_or_non_rider(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    customer = _make_user(db, name="Not A Rider", email="not-rider-p14@example.com", phone="8200000090", role=UserRole.CUSTOMER)

    assert client.get(f"{COD_URL}/{customer.id}", headers=headers).status_code == 404
    assert client.get(f"{COD_URL}/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404


def test_settle_creates_ledger_row_and_audit_log(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_rider(db, "90")
    _make_cod_collection(db, rider=rider, amount=Decimal("500.00"))

    response = client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "300.00", "note": "Handed over in person"})
    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["settled_amount"]) == Decimal("300.00")
    assert Decimal(body["outstanding_amount"]) == Decimal("200.00")
    assert body["status"] == "PARTIAL"

    settlement = db.query(RiderSettlement).filter(RiderSettlement.rider_id == rider.id).one()
    assert settlement.settlement_type == SettlementType.REMITTANCE
    assert settlement.amount == Decimal("300.00")
    assert settlement.note == "Handed over in person"

    # Financial Ledger Validation (Phase 30) — every real financial
    # movement is traceable, not just a status flag: the response's own
    # settlements[0].allocations shows exactly which collected order(s)
    # this settlement discharges.
    settlement_record = next(s for s in body["settlements"] if s["id"] == str(settlement.id))
    assert Decimal(sum(Decimal(a["amount_allocated"]) for a in settlement_record["allocations"])) == Decimal("300.00")

    log = db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "rider", AdminAuditLog.target_id == str(rider.id), AdminAuditLog.action == "cod.settle").one()
    assert log.admin_id == admin.id
    assert log.previous_state == "500.00"
    assert log.new_state == "200.00"


def test_settle_cannot_exceed_outstanding(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "91")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))

    response = client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "150.00"})
    assert response.status_code == 409

    count = db.query(RiderSettlement).filter(RiderSettlement.rider_id == rider.id).count()
    assert count == 0


def test_settle_rejects_zero_or_negative_amount(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "92")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))

    assert client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "0"}).status_code == 422
    assert client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "-10"}).status_code == 422


def test_settle_when_nothing_outstanding_is_conflict(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "93")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))
    db.add(RiderSettlement(rider_id=rider.id, settlement_type=SettlementType.REMITTANCE, amount=Decimal("100.00")))
    db.commit()

    response = client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "1.00"})
    assert response.status_code == 409


def test_multiple_partial_settlements_accumulate_via_new_rows_never_overwritten(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "94")
    _make_cod_collection(db, rider=rider, amount=Decimal("1000.00"))

    client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "300.00"})
    client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "200.00"})

    rows = db.query(RiderSettlement).filter(RiderSettlement.rider_id == rider.id).all()
    assert len(rows) == 2
    assert sorted(r.amount for r in rows) == [Decimal("200.00"), Decimal("300.00")]

    detail = client.get(f"{COD_URL}/{rider.id}", headers=headers)
    assert Decimal(detail.json()["settled_amount"]) == Decimal("500.00")
    assert Decimal(detail.json()["outstanding_amount"]) == Decimal("500.00")


def test_settle_requires_admin(client):
    db = _db(client)
    rider = _make_rider(db, "95")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))
    token = create_access_token(rider.id)

    response = client.post(
        f"{COD_URL}/{rider.id}/settle", headers={"Authorization": f"Bearer {token}"}, json={"amount": "50.00"}
    )
    assert response.status_code == 403


def test_settle_404_for_non_rider(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    customer = _make_user(db, name="Not A Rider Settle", email="not-rider-settle-p14@example.com", phone="8200000096", role=UserRole.CUSTOMER)

    response = client.post(f"{COD_URL}/{customer.id}/settle", headers=headers, json={"amount": "10.00"})
    assert response.status_code == 404


def test_settle_exceeding_outstanding_is_logged_as_a_cod_issue(client, caplog):
    """Logging & Error Handling (Phase 26) — an over-settlement attempt is
    a COD issue and must reach a server-side log."""
    import logging

    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_rider(db, "97")
    _make_cod_collection(db, rider=rider, amount=Decimal("100.00"))

    with caplog.at_level(logging.WARNING):
        response = client.post(f"{COD_URL}/{rider.id}/settle", headers=headers, json={"amount": "150.00"})
    assert response.status_code == 409
    assert any("COD issue" in r.message for r in caplog.records)
