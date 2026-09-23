"""Admin Portal — Phase 5: Restaurant Owner Management."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

OWNERS_URL = "/api/v1/admin/restaurant-owners"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p5@example.com", phone="9300000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers_with_admin(db):
    admin = _make_user(db, name="Admin", email="admin-p23-owner@example.com", phone="9300000002", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return admin, {"Authorization": f"Bearer {token}"}


def _make_restaurant(db, *, owner_id, name):
    restaurant = Restaurant(
        owner_id=owner_id, name=name, phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_list_owners_requires_admin(client):
    db = _db(client)
    owner = _make_user(db, name="Someone Owner", email="someone-owner-p5@example.com", phone="9300000010", role=UserRole.RESTAURANT_OWNER)
    token = create_access_token(owner.id)
    assert client.get(OWNERS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(OWNERS_URL).status_code == 401


def test_list_owners_includes_restaurant_association(client):
    db = _db(client)
    headers = _admin_headers(db)
    with_restaurant = _make_user(db, name="Has Restaurant", email="has-rest-p5@example.com", phone="9300000020", role=UserRole.RESTAURANT_OWNER)
    _make_restaurant(db, owner_id=with_restaurant.id, name="Owned Diner")
    without_restaurant = _make_user(db, name="No Restaurant", email="no-rest-p5@example.com", phone="9300000021", role=UserRole.RESTAURANT_OWNER)

    response = client.get(OWNERS_URL, headers=headers)
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()["items"]}

    assert len(items["Has Restaurant"]["restaurants"]) == 1
    assert items["Has Restaurant"]["restaurants"][0]["name"] == "Owned Diner"
    assert items["No Restaurant"]["restaurants"] == []


def test_list_owners_excludes_non_owner_roles(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_user(db, name="A Customer", email="a-cust-p5@example.com", phone="9300000030", role=UserRole.CUSTOMER)
    _make_user(db, name="A Rider", email="a-rider-p5@example.com", phone="9300000031", role=UserRole.RIDER)

    response = client.get(OWNERS_URL, headers=headers)
    names = [item["name"] for item in response.json()["items"]]
    assert "A Customer" not in names
    assert "A Rider" not in names


def test_list_owners_search(client):
    db = _db(client)
    headers = _admin_headers(db)
    _make_user(db, name="Findable Owner", email="findable-owner-p5@example.com", phone="9300000040", role=UserRole.RESTAURANT_OWNER)
    _make_user(db, name="Other Owner", email="other-owner-p5@example.com", phone="9300000041", role=UserRole.RESTAURANT_OWNER)

    response = client.get(OWNERS_URL, headers=headers, params={"search": "Findable"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Findable Owner"]


def test_list_owners_status_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    active = _make_user(db, name="Active Owner", email="active-owner-p5@example.com", phone="9300000050", role=UserRole.RESTAURANT_OWNER)
    suspended = _make_user(db, name="Suspended Owner", email="suspended-owner-p5@example.com", phone="9300000051", role=UserRole.RESTAURANT_OWNER)
    db.query(User).filter(User.id == suspended.id).update({User.is_active: False})
    db.commit()

    response = client.get(OWNERS_URL, headers=headers, params={"status": "SUSPENDED"})
    names = [item["name"] for item in response.json()["items"]]
    assert names == ["Suspended Owner"]

    response = client.get(OWNERS_URL, headers=headers, params={"status": "ACTIVE"})
    names = [item["name"] for item in response.json()["items"]]
    assert "Active Owner" in names
    assert "Suspended Owner" not in names


def test_list_owners_has_restaurant_filter(client):
    db = _db(client)
    headers = _admin_headers(db)
    with_restaurant = _make_user(db, name="Filter Has Restaurant", email="filter-has-p5@example.com", phone="9300000060", role=UserRole.RESTAURANT_OWNER)
    _make_restaurant(db, owner_id=with_restaurant.id, name="Filter Diner")
    _make_user(db, name="Filter No Restaurant", email="filter-no-p5@example.com", phone="9300000061", role=UserRole.RESTAURANT_OWNER)

    response = client.get(OWNERS_URL, headers=headers, params={"has_restaurant": "true"})
    names = [item["name"] for item in response.json()["items"]]
    assert "Filter Has Restaurant" in names
    assert "Filter No Restaurant" not in names

    response = client.get(OWNERS_URL, headers=headers, params={"has_restaurant": "false"})
    names = [item["name"] for item in response.json()["items"]]
    assert "Filter No Restaurant" in names
    assert "Filter Has Restaurant" not in names


def test_get_owner_detail(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _make_user(db, name="Detail Owner", email="detail-owner-p5@example.com", phone="9300000070", role=UserRole.RESTAURANT_OWNER)
    _make_restaurant(db, owner_id=owner.id, name="Detail Diner")

    response = client.get(f"{OWNERS_URL}/{owner.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Detail Owner"
    assert len(body["restaurants"]) == 1


def test_get_owner_detail_404_for_missing_or_wrong_role(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Not An Owner", email="not-owner-p5@example.com", phone="9300000080", role=UserRole.CUSTOMER)

    assert client.get(f"{OWNERS_URL}/{customer.id}", headers=headers).status_code == 404
    assert client.get(f"{OWNERS_URL}/00000000-0000-0000-0000-000000000000", headers=headers).status_code == 404


def test_admin_can_suspend_and_reactivate_owner(client):
    db = _db(client)
    admin, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Toggle Owner", email="toggle-owner-p5@example.com", phone="9300000090", role=UserRole.RESTAURANT_OWNER)

    suspend = client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={"reason": "Policy violation"})
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "SUSPENDED"

    # Validates current state — suspending an already-suspended owner is a 409.
    assert client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={"reason": "again"}).status_code == 409

    reactivate = client.post(f"{OWNERS_URL}/{owner.id}/activate", headers=headers, json={"reason": "Appeal accepted"})
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "ACTIVE"

    entries = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(owner.id)).order_by(AdminAuditLog.created_at).all()
    assert [e.action for e in entries] == ["restaurant_owner.suspend", "restaurant_owner.activate"]
    assert entries[0].admin_id == admin.id
    assert entries[0].reason == "Policy violation"


def test_suspend_requires_a_reason(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="No Reason Owner", email="noreason-owner-p5@example.com", phone="9300000091", role=UserRole.RESTAURANT_OWNER)

    assert client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={}).status_code == 422
    assert client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={"reason": ""}).status_code == 422


def test_old_generic_patch_route_no_longer_exists(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Legacy Owner", email="legacy-owner-p5@example.com", phone="9300000092", role=UserRole.RESTAURANT_OWNER)

    response = client.patch(f"{OWNERS_URL}/{owner.id}", headers=headers, json={"status": "SUSPENDED"})
    assert response.status_code == 405


def test_suspending_owner_does_not_touch_their_restaurant(client):
    """The core safety requirement of this phase: suspending the owner's
    account must never silently modify their restaurant's own state
    (ownership, active flag, or approval status)."""
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Safe Owner", email="safe-owner-p5@example.com", phone="9300000100", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Untouched Diner")

    client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={"reason": "test"})

    db.refresh(restaurant)
    assert restaurant.owner_id == owner.id
    assert restaurant.is_active is True
    assert restaurant.approval_status.value == "APPROVED"


def test_non_admin_cannot_update_owner_status(client):
    db = _db(client)
    owner = _make_user(db, name="Victim Owner", email="victim-owner-p5@example.com", phone="9300000120", role=UserRole.RESTAURANT_OWNER)
    attacker = _make_user(db, name="Attacker Owner", email="attacker-owner-p5@example.com", phone="9300000121", role=UserRole.RESTAURANT_OWNER)
    attacker_token = create_access_token(attacker.id)

    response = client.post(
        f"{OWNERS_URL}/{owner.id}/suspend",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={"reason": "attack"},
    )
    assert response.status_code == 403


def test_suspended_owner_is_locked_out_immediately(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Locked Owner", email="locked-owner-p5@example.com", phone="9300000130", role=UserRole.RESTAURANT_OWNER)
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    assert client.get("/api/v1/auth/me", headers=owner_headers).status_code == 200

    client.post(f"{OWNERS_URL}/{owner.id}/suspend", headers=headers, json={"reason": "test"})

    response = client.get("/api/v1/auth/me", headers=owner_headers)
    assert response.status_code in (401, 403)
