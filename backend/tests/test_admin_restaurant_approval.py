"""Admin Portal — Phase 6: Restaurant Approval state machine.

Expected lifecycle:

    PENDING --approve--> APPROVED --suspend--> SUSPENDED --activate--> APPROVED
    PENDING --reject-->  REJECTED --approve-->  APPROVED

Anything not on one of those arrows must be rejected with 409, mirroring
the rigor Phase 24 applied to the delivery-assignment state machine.
"""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.delivery_partner import ApprovalStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

RESTAURANTS_URL = "/api/v1/admin/restaurants"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p6@example.com", phone="9200000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _make_restaurant(db, *, owner_id, name, approval_status):
    restaurant = Restaurant(
        owner_id=owner_id, name=name, phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"), approval_status=approval_status,
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _owner(db, suffix):
    return _make_user(
        db, name=f"Owner {suffix}", email=f"owner-{suffix}-p6@example.com", phone=f"92000001{suffix}", role=UserRole.RESTAURANT_OWNER
    )


def test_approve_from_pending_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "10").id, name="Pending Diner", approval_status=ApprovalStatus.PENDING)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"


def test_approve_from_rejected_succeeds_and_clears_reason(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "11").id, name="Rejected Diner", approval_status=ApprovalStatus.REJECTED)
    restaurant.rejection_reason = "Missing FSSAI license"
    db.commit()

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"})
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "APPROVED"
    assert body["rejection_reason"] is None


def test_approve_from_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "12").id, name="Already Approved", approval_status=ApprovalStatus.APPROVED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_approve_from_suspended_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "13").id, name="Suspended Restaurant", approval_status=ApprovalStatus.SUSPENDED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_reject_from_pending_requires_reason_and_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "20").id, name="To Be Rejected", approval_status=ApprovalStatus.PENDING)

    missing_reason = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/reject", headers=headers, json={})
    assert missing_reason.status_code == 422

    response = client.post(
        f"{RESTAURANTS_URL}/{restaurant.id}/reject", headers=headers, json={"rejection_reason": "Incomplete documentation"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["approval_status"] == "REJECTED"
    assert body["rejection_reason"] == "Incomplete documentation"


def test_reject_from_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "21").id, name="Live Restaurant", approval_status=ApprovalStatus.APPROVED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/reject", headers=headers, json={"rejection_reason": "test"})
    assert response.status_code == 409


def test_reject_from_suspended_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "22").id, name="Suspended Not Rejectable", approval_status=ApprovalStatus.SUSPENDED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/reject", headers=headers, json={"rejection_reason": "test"})
    assert response.status_code == 409


def test_suspend_from_approved_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "30").id, name="To Suspend", approval_status=ApprovalStatus.APPROVED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "SUSPENDED"


def test_suspend_from_pending_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "31").id, name="Cannot Suspend Pending", approval_status=ApprovalStatus.PENDING)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_suspend_from_rejected_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "32").id, name="Cannot Suspend Rejected", approval_status=ApprovalStatus.REJECTED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_suspend_from_suspended_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "33").id, name="Already Suspended", approval_status=ApprovalStatus.SUSPENDED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_activate_from_suspended_succeeds(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "40").id, name="To Reinstate", approval_status=ApprovalStatus.SUSPENDED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/activate", headers=headers, json={"reason": "test"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"


def test_activate_from_pending_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "41").id, name="Cannot Activate Pending", approval_status=ApprovalStatus.PENDING)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/activate", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_activate_from_rejected_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "42").id, name="Cannot Activate Rejected", approval_status=ApprovalStatus.REJECTED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/activate", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_activate_from_approved_is_conflict(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "43").id, name="Already Live", approval_status=ApprovalStatus.APPROVED)

    response = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/activate", headers=headers, json={"reason": "test"})
    assert response.status_code == 409


def test_full_lifecycle_pending_to_approved_to_suspended_to_approved(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, owner_id=_owner(db, "50").id, name="Full Lifecycle Diner", approval_status=ApprovalStatus.PENDING)

    r1 = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"})
    assert r1.json()["approval_status"] == "APPROVED"

    r2 = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert r2.json()["approval_status"] == "SUSPENDED"

    r3 = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/activate", headers=headers, json={"reason": "test"})
    assert r3.json()["approval_status"] == "APPROVED"


def test_actions_require_admin(client):
    db = _db(client)
    owner = _owner(db, "60")
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Auth Check Diner", approval_status=ApprovalStatus.PENDING)
    owner_token = create_access_token(owner.id)

    for action, payload in (("approve", None), ("reject", {"rejection_reason": "x"}), ("suspend", None), ("activate", None)):
        response = client.post(
            f"{RESTAURANTS_URL}/{restaurant.id}/{action}",
            headers={"Authorization": f"Bearer {owner_token}"},
            json=payload,
        )
        assert response.status_code == 403, action

    for action in ("approve", "reject", "suspend", "activate"):
        assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/{action}").status_code == 401


def test_actions_404_for_missing_restaurant(client):
    db = _db(client)
    headers = _admin_headers(db)
    missing_id = "00000000-0000-0000-0000-000000000000"

    assert client.post(f"{RESTAURANTS_URL}/{missing_id}/approve", headers=headers, json={"reason": "test"}).status_code == 404
    assert client.post(f"{RESTAURANTS_URL}/{missing_id}/reject", headers=headers, json={"rejection_reason": "x"}).status_code == 404
    assert client.post(f"{RESTAURANTS_URL}/{missing_id}/suspend", headers=headers, json={"reason": "test"}).status_code == 404
    assert client.post(f"{RESTAURANTS_URL}/{missing_id}/activate", headers=headers, json={"reason": "test"}).status_code == 404


def test_suspended_restaurant_is_hidden_from_customers(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _owner(db, "70")
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Hide Me", approval_status=ApprovalStatus.APPROVED)

    customer = _make_user(db, name="Browsing Cust P6", email="browsing-cust-p6@example.com", phone="9200000071", role=UserRole.CUSTOMER)
    customer_headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    before = client.get("/api/v1/customer/restaurants", headers=customer_headers)
    assert any(r["id"] == str(restaurant.id) for r in before.json())

    client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})

    after = client.get("/api/v1/customer/restaurants", headers=customer_headers)
    assert not any(r["id"] == str(restaurant.id) for r in after.json())
