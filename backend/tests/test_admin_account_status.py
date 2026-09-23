"""Admin Portal — Phase 23: User Status & Platform Controls.

The genuinely NEW capability this phase adds is the rider account-level
on/off switch (User.is_active) — distinct from Phase 7/9's approval_status
suspend/activate, which only ever governed delivery eligibility, not login
access. Customer and restaurant owner already had a loose PATCH-based
is_active toggle (Phase 3/5); this phase replaces those with validated,
audited POST actions (covered in tests/test_admin_customers.py and
tests/test_admin_restaurant_owners.py respectively). This file focuses on
the rider account actions and on cross-cutting guarantees shared by all
four target types: current-state validation, reason requirement, and
audit logging.
"""

import uuid

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
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


def _admin(db):
    admin = _make_user(db, name="Admin", email=f"admin-p23-{uuid.uuid4().hex[:8]}@example.com", phone=f"77{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _rider(db, *, approved=False):
    rider = _make_user(db, name="Rider", email=f"rider-p23-{uuid.uuid4().hex[:8]}@example.com", phone=f"78{uuid.uuid4().hex[:8]}", role=UserRole.RIDER)
    if approved:
        db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
        db.commit()
    return rider


def test_rider_deactivate_reactivate_requires_admin(client):
    db = _db(client)
    rider = _rider(db)
    customer = _make_user(db, name="Not Admin", email="not-admin-p23@example.com", phone="7700000001", role=UserRole.CUSTOMER)
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    assert client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "x"}).status_code == 403
    assert client.post(f"{RIDERS_URL}/{rider.id}/deactivate", json={"reason": "x"}).status_code == 401
    assert client.post(f"{RIDERS_URL}/{rider.id}/reactivate", headers=headers, json={"reason": "x"}).status_code == 403


def test_rider_deactivate_blocks_login_reactivate_restores_it(client):
    db = _db(client)
    admin, headers = _admin(db)
    rider = _rider(db, approved=True)
    rider_headers = {"Authorization": f"Bearer {create_access_token(rider.id)}"}

    assert client.get("/api/v1/auth/me", headers=rider_headers).status_code == 200

    response = client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "Multiple customer complaints"})
    assert response.status_code == 200
    assert response.json()["is_active"] is False

    assert client.get("/api/v1/auth/me", headers=rider_headers).status_code in (401, 403)

    reactivate = client.post(f"{RIDERS_URL}/{rider.id}/reactivate", headers=headers, json={"reason": "Investigation closed, no violation found"})
    assert reactivate.status_code == 200
    assert reactivate.json()["is_active"] is True

    entries = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(rider.id), AdminAuditLog.target_type == "rider").order_by(AdminAuditLog.created_at).all()
    assert [e.action for e in entries] == ["rider.deactivate", "rider.reactivate"]
    assert entries[0].admin_id == admin.id
    assert entries[0].reason == "Multiple customer complaints"
    assert entries[0].previous_state == "True"
    assert entries[0].new_state == "False"


def test_rider_deactivate_does_not_touch_approval_status(client):
    """The account-level switch (Phase 23) and the delivery-eligibility
    switch (Phase 7/9) are fully independent — deactivating a rider's
    account must never silently change their approval_status, and vice
    versa the pre-existing approval suspend must never touch is_active."""
    db = _db(client)
    _, headers = _admin(db)
    rider = _rider(db, approved=True)

    client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "test"})
    partner = db.query(DeliveryPartner).filter(DeliveryPartner.user_id == rider.id).one()
    assert partner.approval_status == ApprovalStatus.APPROVED

    db.refresh(rider)
    rider.is_active = True
    db.commit()
    client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers)
    db.refresh(rider)
    assert rider.is_active is True


def test_rider_deactivate_validates_current_state(client):
    db = _db(client)
    _, headers = _admin(db)
    rider = _rider(db)

    assert client.post(f"{RIDERS_URL}/{rider.id}/reactivate", headers=headers, json={"reason": "x"}).status_code == 409

    first = client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "x"})
    assert first.status_code == 200
    second = client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "x"})
    assert second.status_code == 409


def test_rider_deactivate_requires_a_reason(client):
    db = _db(client)
    _, headers = _admin(db)
    rider = _rider(db)

    assert client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={}).status_code == 422
    assert client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": ""}).status_code == 422


def test_rider_deactivate_404_for_non_rider(client):
    db = _db(client)
    _, headers = _admin(db)
    customer = _make_user(db, name="Cust", email="cust-p23@example.com", phone="7700000010", role=UserRole.CUSTOMER)

    assert client.post(f"{RIDERS_URL}/{customer.id}/deactivate", headers=headers, json={"reason": "x"}).status_code == 404


def test_audit_log_entries_are_visible_through_phase_21_endpoints(client):
    db = _db(client)
    admin, headers = _admin(db)
    rider = _rider(db)

    client.post(f"{RIDERS_URL}/{rider.id}/deactivate", headers=headers, json={"reason": "Cross-phase visibility check"})

    listed = client.get("/api/v1/admin/audit-logs?action=rider.deactivate", headers=headers).json()
    assert listed["total"] == 1
    assert listed["items"][0]["reason"] == "Cross-phase visibility check"
    assert listed["items"][0]["ip_address"]
