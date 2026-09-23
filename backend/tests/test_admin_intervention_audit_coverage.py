"""Integration Phase 21 — Admin Intervention Validation.

Every administrative intervention must validate current state, validate
the requested action, record the admin's id, record a reason, update the
entity, and create an audit log entry. Order cancellation, customer
suspension, and COD settlement already had this — confirmed here for
completeness. Restaurant approval/suspension and rider approval/
suspension did NOT: approve/reject/suspend/activate on both entities
mutated approval_status with no admin_id, no required reason (for three
of the four actions), and no audit log entry at all. This file locks in
the fix.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.delivery_partner import ApprovalStatus, DeliveryPartner
from app.models.order import Order, OrderStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

ORDERS_URL = "/api/v1/admin/orders"
RESTAURANTS_URL = "/api/v1/admin/restaurants"
RIDERS_URL = "/api/v1/admin/riders"
CUSTOMERS_URL = "/api/v1/admin/customers"
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
    admin = _make_user(db, name="Admin", email=f"admin-p21-{uuid.uuid4().hex[:8]}@example.com", phone=f"74{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _audit_entry(db, *, target_id, action):
    return db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(target_id), AdminAuditLog.action == action).one()


def test_restaurant_approve_records_admin_id_reason_and_audit_log(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    owner = _make_user(db, name="Owner", email="owner-p21a@example.com", phone="9500000001", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name="Pending Diner", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        approval_status=ApprovalStatus.PENDING,
    )
    db.add(restaurant)
    db.commit()

    # Requested action validated: missing reason is rejected before anything mutates.
    missing_reason = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={})
    assert missing_reason.status_code == 422

    response = client.post(
        f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "Documents verified"}
    )
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"

    entry = _audit_entry(db, target_id=restaurant.id, action="restaurant.approve")
    assert entry.admin_id == admin.id
    assert entry.reason == "Documents verified"
    assert entry.previous_state == "PENDING"
    assert entry.new_state == "APPROVED"
    assert entry.target_type == "restaurant"


def test_restaurant_suspend_validates_current_state_and_is_audited(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    owner = _make_user(db, name="Owner", email="owner-p21b@example.com", phone="9500000002", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name="Live Diner", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        approval_status=ApprovalStatus.APPROVED,
    )
    db.add(restaurant)
    db.commit()

    suspend = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "Repeated food safety complaints"})
    assert suspend.status_code == 200
    assert suspend.json()["approval_status"] == "SUSPENDED"

    entry = _audit_entry(db, target_id=restaurant.id, action="restaurant.suspend")
    assert entry.admin_id == admin.id
    assert entry.reason == "Repeated food safety complaints"
    assert entry.previous_state == "APPROVED"
    assert entry.new_state == "SUSPENDED"

    # Validate current state: an already-suspended restaurant can't be suspended again.
    second = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "x"})
    assert second.status_code == 409
    # No orphan audit entry for the rejected second attempt.
    assert db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(restaurant.id), AdminAuditLog.action == "restaurant.suspend").count() == 1


def test_rider_approve_records_admin_id_reason_and_audit_log(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_user(db, name="Pending Rider", email="rider-p21a@example.com", phone="9500000010", role=UserRole.RIDER)

    response = client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "All documents verified"})
    assert response.status_code == 200
    assert response.json()["approval_status"] == "APPROVED"

    entry = _audit_entry(db, target_id=rider.id, action="rider.approve")
    assert entry.admin_id == admin.id
    assert entry.reason == "All documents verified"
    assert entry.previous_state == "PENDING"
    assert entry.new_state == "APPROVED"
    assert entry.target_type == "rider"


def test_rider_suspend_validates_current_state_and_is_audited(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_user(db, name="Live Rider", email="rider-p21b@example.com", phone="9500000011", role=UserRole.RIDER)
    db.add(DeliveryPartner(user_id=rider.id, approval_status=ApprovalStatus.APPROVED))
    db.commit()

    suspend = client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "Customer safety complaint"})
    assert suspend.status_code == 200
    assert suspend.json()["approval_status"] == "SUSPENDED"

    entry = _audit_entry(db, target_id=rider.id, action="rider.suspend")
    assert entry.admin_id == admin.id
    assert entry.reason == "Customer safety complaint"
    assert entry.previous_state == "APPROVED"
    assert entry.new_state == "SUSPENDED"

    # Validate requested action: suspend is only valid from APPROVED.
    invalid = client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "x"})
    assert invalid.status_code == 409
    assert db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(rider.id), AdminAuditLog.action == "rider.suspend").count() == 1


def test_rider_reject_reason_doubles_as_audit_reason_and_partner_field(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    rider = _make_user(db, name="Rejected Rider", email="rider-p21c@example.com", phone="9500000012", role=UserRole.RIDER)

    response = client.post(f"{RIDERS_URL}/{rider.id}/reject", headers=headers, json={"rejection_reason": "Blurry license photo"})
    assert response.status_code == 200
    assert response.json()["rejection_reason"] == "Blurry license photo"

    entry = _audit_entry(db, target_id=rider.id, action="rider.reject")
    assert entry.admin_id == admin.id
    assert entry.reason == "Blurry license photo"


def test_all_seven_named_interventions_are_visible_in_the_audit_log(client):
    """Sweeps every intervention this phase explicitly names and confirms
    each produced exactly one listable, admin-attributed, reasoned entry."""
    db = _db(client)
    admin, headers = _admin_headers(db)

    # Order cancellation.
    order = Order(
        user_id=uuid.uuid4(), customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.PLACED,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    assert client.post(f"{ORDERS_URL}/{order.id}/cancel", headers=headers, json={"reason": "test"}).status_code == 200

    # Restaurant approval + suspension.
    owner = _make_user(db, name="Owner", email="owner-p21d@example.com", phone="9500000020", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name="Sweep Diner", phone="9876543210", address="Main Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        approval_status=ApprovalStatus.PENDING,
    )
    db.add(restaurant)
    db.commit()
    assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/approve", headers=headers, json={"reason": "test"}).status_code == 200
    assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"}).status_code == 200

    # Rider approval + suspension.
    rider = _make_user(db, name="Sweep Rider", email="rider-p21d@example.com", phone="9500000021", role=UserRole.RIDER)
    assert client.post(f"{RIDERS_URL}/{rider.id}/approve", headers=headers, json={"reason": "test"}).status_code == 200
    assert client.post(f"{RIDERS_URL}/{rider.id}/suspend", headers=headers, json={"reason": "test"}).status_code == 200

    # Customer suspension.
    customer = _make_user(db, name="Sweep Customer", email="cust-p21d@example.com", phone="9500000022", role=UserRole.CUSTOMER)
    assert client.post(f"{CUSTOMERS_URL}/{customer.id}/suspend", headers=headers, json={"reason": "test"}).status_code == 200

    # COD settlement.
    cod_rider = _make_user(db, name="COD Rider", email="cod-rider-p21d@example.com", phone="9500000023", role=UserRole.RIDER)
    from app.models.payment import Payment, PaymentProvider

    cod_order = Order(
        user_id=uuid.uuid4(), customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=OrderStatus.DELIVERED,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(cod_order)
    db.commit()
    db.add(Payment(
        order_id=cod_order.id, user_id=cod_order.user_id, provider=PaymentProvider.COD,
        amount=Decimal("130.00"), collected_by_rider_id=cod_rider.id,
    ))
    db.commit()
    assert client.post(f"{COD_URL}/{cod_rider.id}/settle", headers=headers, json={"amount": "50.00", "note": "test"}).status_code == 200

    # Every one of the seven actions above produced exactly one audit entry,
    # all attributed to this admin, all with a non-empty reason.
    expected_actions = {
        "order.cancel", "restaurant.approve", "restaurant.suspend",
        "rider.approve", "rider.suspend", "customer.suspend", "cod.settle",
    }
    entries = db.query(AdminAuditLog).filter(AdminAuditLog.action.in_(expected_actions)).all()
    found_actions = {e.action for e in entries}
    assert found_actions == expected_actions
    for entry in entries:
        assert entry.admin_id == admin.id
        assert entry.reason
