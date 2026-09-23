"""Admin Portal — Phase 7: Rider Management."""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner, VehicleType
from app.models.order import Order, OrderStatus
from app.models.review import Review, ReviewTarget
from app.models.rider_earning import EarningType, RiderEarning
from app.models.user import User, UserRole

RIDERS_URL = "/api/v1/admin/riders"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p7@example.com", phone="9100000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _make_rider(db, *, name, email, phone):
    return _make_user(db, name=name, email=email, phone=phone, role=UserRole.RIDER)


def _make_partner(db, *, rider_id, approval_status=ApprovalStatus.PENDING, is_online=False, vehicle_type=None, vehicle_number=None):
    partner = DeliveryPartner(
        user_id=rider_id, approval_status=approval_status, is_online=is_online,
        vehicle_type=vehicle_type, vehicle_number=vehicle_number,
    )
    db.add(partner)
    db.commit()
    db.refresh(partner)
    return partner


def _make_delivered_order(db, *, rider_id, delivery_fee=Decimal("40.00")):
    order = Order(
        user_id=uuid.uuid4(), rider_id=rider_id, customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.DELIVERED,
        subtotal=Decimal("100.00"), delivery_fee=delivery_fee, total=Decimal("140.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", state="TS", postal_code="123456",
        latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    db.add(RiderEarning(rider_id=rider_id, order_id=order.id, earning_type=EarningType.DELIVERY_FEE, amount=delivery_fee))
    db.commit()
    return order


def test_list_riders_requires_admin(client):
    db = _db(client)
    rider = _make_rider(db, name="Some Rider", email="some-rider-p7@example.com", phone="9100000010")
    token = create_access_token(rider.id)
    assert client.get(RIDERS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(RIDERS_URL).status_code == 401


def test_rider_without_partner_row_defaults_to_pending_offline(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_rider(db, name="Fresh Rider", email="fresh-rider-p7@example.com", phone="9100000020")

    response = client.get(RIDERS_URL, headers=headers)
    assert response.status_code == 200
    match = next(item for item in response.json()["items"] if item["name"] == "Fresh Rider")
    assert match["approval_status"] == "PENDING"
    assert match["is_online"] is False
    assert match["vehicle_type"] is None
    assert match["rating"] == 0.0
    assert match["deliveries_count"] == 0
    assert match["total_earnings"] == "0.00"


def test_list_riders_includes_full_profile(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Full Profile Rider", email="full-rider-p7@example.com", phone="9100000030")
    _make_partner(
        db, rider_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True,
        vehicle_type=VehicleType.BIKE, vehicle_number="KA01AB1234",
    )
    order = _make_delivered_order(db, rider_id=rider.id, delivery_fee=Decimal("40.00"))
    customer = _make_user(db, name="Rating Cust", email="rating-cust-p7@example.com", phone="9100000031", role=UserRole.CUSTOMER)
    db.add(Review(user_id=customer.id, order_id=order.id, rider_id=rider.id, target_type=ReviewTarget.RESTAURANT, target_id="rest-1", rating=5, delivery_rating=4))
    db.commit()

    response = client.get(RIDERS_URL, headers=headers)
    match = next(item for item in response.json()["items"] if item["id"] == str(rider.id))
    assert match["approval_status"] == "APPROVED"
    assert match["is_online"] is True
    assert match["vehicle_type"] == "BIKE"
    assert match["vehicle_number"] == "KA01AB1234"
    assert match["rating"] == 4.0
    assert match["deliveries_count"] == 1
    assert Decimal(match["total_earnings"]) == Decimal("40.00")


def test_list_riders_search(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_rider(db, name="Findable Rider", email="findable-rider-p7@example.com", phone="9100000040")
    _make_rider(db, name="Other Rider", email="other-rider-p7@example.com", phone="9100000041")

    response = client.get(RIDERS_URL, headers=headers, params={"search": "Findable"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Findable Rider"]


def test_list_riders_approval_status_filter_includes_partnerless_as_pending(client):
    db = _db(client)
    headers = _admin_headers(db)
    no_partner = _make_rider(db, name="No Partner Rider", email="no-partner-p7@example.com", phone="9100000050")
    approved = _make_rider(db, name="Approved Rider Filter", email="approved-filter-p7@example.com", phone="9100000051")
    _make_partner(db, rider_id=approved.id, approval_status=ApprovalStatus.APPROVED)

    response = client.get(RIDERS_URL, headers=headers, params={"approval_status": "PENDING"})
    names = [item["name"] for item in response.json()["items"]]
    assert "No Partner Rider" in names
    assert "Approved Rider Filter" not in names

    response = client.get(RIDERS_URL, headers=headers, params={"approval_status": "APPROVED"})
    names = [item["name"] for item in response.json()["items"]]
    assert "Approved Rider Filter" in names
    assert "No Partner Rider" not in names


def test_list_riders_online_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    online = _make_rider(db, name="Online Rider", email="online-rider-p7@example.com", phone="9100000060")
    _make_partner(db, rider_id=online.id, approval_status=ApprovalStatus.APPROVED, is_online=True)
    _make_rider(db, name="Offline No Partner Rider", email="offline-rider-p7@example.com", phone="9100000061")

    response = client.get(RIDERS_URL, headers=headers, params={"is_online": "true"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Online Rider"]


def test_get_rider_detail_includes_documents_and_deliveries(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Detail Rider", email="detail-rider-p7@example.com", phone="9100000070")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.APPROVED)
    _make_delivered_order(db, rider_id=rider.id)

    rider_token = create_access_token(rider.id)
    client.post(
        "/api/v1/rider/documents", headers={"Authorization": f"Bearer {rider_token}"},
        json={"document_type": "DRIVING_LICENSE", "document_url": "https://example.com/dl.jpg"},
    )

    response = client.get(f"{RIDERS_URL}/{rider.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["documents"]) == 1
    assert len(body["recent_deliveries"]) == 1


def test_get_rider_detail_404_for_missing_or_wrong_role(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Not A Rider", email="not-rider-p7@example.com", phone="9100000080", role=UserRole.CUSTOMER)

    assert client.get(f"{RIDERS_URL}/{customer.id}", headers=headers).status_code == 404
    assert client.get(f"{RIDERS_URL}/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404


def test_approve_from_pending_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="To Approve", email="to-approve-p7@example.com", phone="9100000090")

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "approve", "reason": "test"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"


def test_approve_from_rejected_clears_reason(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Rejected To Approve", email="rejected-approve-p7@example.com", phone="9100000091")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.REJECTED)
    db.query(DeliveryPartner).filter(DeliveryPartner.user_id == rider.id).update({"rejection_reason": "bad docs"})
    db.commit()

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "approve", "reason": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "APPROVED"
    assert body["rejection_reason"] is None


def test_approve_from_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Already Approved Rider", email="already-approved-p7@example.com", phone="9100000092")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.APPROVED)

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "approve", "reason": "test"})
    assert response.status_code == 409


def test_reject_requires_reason_and_succeeds_from_pending(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="To Reject", email="to-reject-p7@example.com", phone="9100000100")

    missing = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "reject"})
    assert missing.status_code == 422

    response = client.patch(
        f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "reject", "reason": "Bad photo"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "REJECTED"
    assert body["rejection_reason"] == "Bad photo"


def test_reject_from_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Live Rider Reject", email="live-rider-reject-p7@example.com", phone="9100000101")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.APPROVED)

    response = client.patch(
        f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "reject", "reason": "x"}
    )
    assert response.status_code == 409


def test_suspend_from_approved_succeeds_and_forces_offline(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="To Suspend", email="to-suspend-p7@example.com", phone="9100000110")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.APPROVED, is_online=True)

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "suspend", "reason": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "SUSPENDED"
    assert body["is_online"] is False


def test_suspend_from_pending_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Cannot Suspend Pending", email="cannot-suspend-pending-p7@example.com", phone="9100000111")

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "suspend", "reason": "test"})
    assert response.status_code == 409


def test_activate_from_suspended_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="To Reinstate", email="to-reinstate-p7@example.com", phone="9100000120")
    _make_partner(db, rider_id=rider.id, approval_status=ApprovalStatus.SUSPENDED)

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "activate", "reason": "test"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"


def test_activate_from_pending_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Cannot Activate Pending", email="cannot-activate-pending-p7@example.com", phone="9100000121")

    response = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "activate", "reason": "test"})
    assert response.status_code == 409


def test_full_lifecycle_pending_to_approved_to_suspended_to_approved(client):
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Full Lifecycle Rider", email="full-lifecycle-p7@example.com", phone="9100000130")

    r1 = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "approve", "reason": "test"})
    assert r1.json()["approval_status"] == "APPROVED"

    r2 = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "suspend", "reason": "test"})
    assert r2.json()["approval_status"] == "SUSPENDED"

    r3 = client.patch(f"{RIDERS_URL}/{rider.id}", headers=headers, json={"action": "activate", "reason": "test"})
    assert r3.json()["approval_status"] == "APPROVED"


def test_non_admin_cannot_update_rider(client):
    db = _db(client)
    rider = _make_rider(db, name="Victim Rider", email="victim-rider-p7@example.com", phone="9100000140")
    attacker = _make_rider(db, name="Attacker Rider", email="attacker-rider-p7@example.com", phone="9100000141")
    attacker_token = create_access_token(attacker.id)

    response = client.patch(
        f"{RIDERS_URL}/{rider.id}",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={"action": "approve", "reason": "test"},
    )
    assert response.status_code == 403


def test_update_action_404s_for_missing_rider(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(
        f"{RIDERS_URL}/00000000-0000-0000-0000-000000000000", headers=headers, json={"action": "approve", "reason": "test"}
    )
    assert response.status_code == 404


def test_legacy_verification_endpoint_still_works_unvalidated(client):
    """Phase 7 moved this route's code, but deliberately kept its behavior
    (no transition validation) — pre-existing Rider Portal infrastructure
    this phase didn't ask to change."""
    db = _db(client)
    headers = _admin_headers(db)
    rider = _make_rider(db, name="Legacy Path Rider", email="legacy-path-p7@example.com", phone="9100000150")

    response = client.patch(
        f"{RIDERS_URL}/{rider.id}/verification", headers=headers, json={"approval_status": "APPROVED"}
    )
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"
