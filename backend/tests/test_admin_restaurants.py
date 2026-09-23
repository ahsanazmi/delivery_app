"""Admin Portal — Phase 4: Restaurant Management."""

from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.admin_audit_log import AdminAuditLog
from app.models.delivery_partner import ApprovalStatus
from app.models.order import Order, OrderStatus
from app.models.product import Product
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
    admin = _make_user(db, name="Admin", email="admin-p4@example.com", phone="9400000001", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return {"Authorization": f"Bearer {token}"}


def _admin_headers_with_admin(db):
    admin = _make_user(db, name="Admin", email="admin-p23-restaurant@example.com", phone="9400000002", role=UserRole.ADMIN)
    token = create_access_token(admin.id)
    return admin, {"Authorization": f"Bearer {token}"}


def _make_restaurant(db, *, owner_id, name, is_active=True, is_open=True, approval_status=ApprovalStatus.APPROVED, rating=Decimal("4.50")):
    restaurant = Restaurant(
        owner_id=owner_id, name=name, phone="9876500000", email=f"{name.lower().replace(' ', '')}@example.com",
        address="Addr", latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
        is_active=is_active, is_open=is_open, approval_status=approval_status, average_rating=rating,
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _make_order(db, *, user_id, restaurant_id, status, total, order_number):
    order = Order(
        user_id=user_id, customer_name="Cust", customer_email="cust@example.com",
        restaurant_id=str(restaurant_id), restaurant_name="Some Restaurant",
        order_number=order_number, status=status, subtotal=total, delivery_fee=Decimal("0.00"), total=total,
        payment_method="cod", address_line="123 Main St", city="Testville", state="TS", postal_code="123456",
        latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def test_list_restaurants_requires_admin(client):
    db = _db(client)
    owner = _make_user(db, name="Owner", email="owner-auth-p4@example.com", phone="9400000010", role=UserRole.RESTAURANT_OWNER)
    token = create_access_token(owner.id)
    response = client.get(RESTAURANTS_URL, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    assert client.get(RESTAURANTS_URL).status_code == 401


def test_list_restaurants_includes_order_stats_and_owner(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _make_user(db, name="Owner One", email="owner-one-p4@example.com", phone="9400000020", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Chai Corner")
    customer = _make_user(db, name="Cust P4", email="cust-p4@example.com", phone="9400000021", role=UserRole.CUSTOMER)

    _make_order(db, user_id=customer.id, restaurant_id=restaurant.id, status=OrderStatus.DELIVERED, total=Decimal("120.00"), order_number="ORD-P4-1")
    _make_order(db, user_id=customer.id, restaurant_id=restaurant.id, status=OrderStatus.CANCELLED, total=Decimal("999.00"), order_number="ORD-P4-2")

    response = client.get(RESTAURANTS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    match = next(item for item in body["items"] if item["id"] == str(restaurant.id))
    assert match["owner_name"] == "Owner One"
    assert match["order_count"] == 2
    assert Decimal(match["total_revenue"]) == Decimal("120.00")
    assert match["status"] == "ACTIVE"
    assert match["approval_status"] == "APPROVED"
    assert match["is_open"] is True


def test_list_restaurants_search_and_filters(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _make_user(db, name="Owner Two", email="owner-two-p4@example.com", phone="9400000030", role=UserRole.RESTAURANT_OWNER)
    _make_restaurant(db, owner_id=owner.id, name="Findable Diner")
    _make_restaurant(db, owner_id=owner.id, name="Other Place", is_active=False)
    _make_restaurant(db, owner_id=owner.id, name="Closed Place", is_open=False)
    _make_restaurant(db, owner_id=owner.id, name="Suspended Place", approval_status=ApprovalStatus.SUSPENDED)

    r = client.get(RESTAURANTS_URL, headers=headers, params={"search": "Findable"})
    assert [i["name"] for i in r.json()["items"]] == ["Findable Diner"]

    r = client.get(RESTAURANTS_URL, headers=headers, params={"status": "INACTIVE"})
    assert [i["name"] for i in r.json()["items"]] == ["Other Place"]

    r = client.get(RESTAURANTS_URL, headers=headers, params={"is_open": "false"})
    assert [i["name"] for i in r.json()["items"]] == ["Closed Place"]

    r = client.get(RESTAURANTS_URL, headers=headers, params={"approval_status": "SUSPENDED"})
    assert [i["name"] for i in r.json()["items"]] == ["Suspended Place"]


def test_get_restaurant_detail_includes_owner_menu_and_orders(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _make_user(db, name="Detail Owner", email="detail-owner-p4@example.com", phone="9400000040", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Detail Diner")
    db.add(Product(restaurant_id=restaurant.id, name="Masala Dosa", price=Decimal("90.00")))
    db.commit()
    customer = _make_user(db, name="Detail Cust", email="detail-cust-p4@example.com", phone="9400000041", role=UserRole.CUSTOMER)
    _make_order(db, user_id=customer.id, restaurant_id=restaurant.id, status=OrderStatus.DELIVERED, total=Decimal("90.00"), order_number="ORD-P4-DETAIL")

    response = client.get(f"{RESTAURANTS_URL}/{restaurant.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["owner_email"] == "detail-owner-p4@example.com"
    assert len(body["menu"]) == 1
    assert body["menu"][0]["name"] == "Masala Dosa"
    assert len(body["recent_orders"]) == 1
    assert Decimal(body["total_revenue"]) == Decimal("90.00")


def test_get_restaurant_detail_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.get(f"{RESTAURANTS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_admin_can_deactivate_and_reactivate_restaurant(client):
    db = _db(client)
    admin, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Toggle Owner", email="toggle-owner-p4@example.com", phone="9400000050", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Togglable Place")

    deactivate = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/deactivate", headers=headers, json={"reason": "Health code violation"})
    assert deactivate.status_code == 200
    assert deactivate.json()["status"] == "INACTIVE"

    # Validates current state — deactivating an already-inactive restaurant is a 409.
    assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/deactivate", headers=headers, json={"reason": "again"}).status_code == 409

    reactivate = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/reactivate", headers=headers, json={"reason": "Issue resolved"})
    assert reactivate.status_code == 200
    assert reactivate.json()["status"] == "ACTIVE"

    entries = db.query(AdminAuditLog).filter(AdminAuditLog.target_id == str(restaurant.id)).order_by(AdminAuditLog.created_at).all()
    assert [e.action for e in entries] == ["restaurant.deactivate", "restaurant.reactivate"]
    assert entries[0].admin_id == admin.id
    assert entries[0].reason == "Health code violation"


def test_deactivate_requires_a_reason(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="No Reason Owner", email="noreason-owner-p4@example.com", phone="9400000051", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="No Reason Place")

    assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/deactivate", headers=headers, json={}).status_code == 422
    assert client.post(f"{RESTAURANTS_URL}/{restaurant.id}/deactivate", headers=headers, json={"reason": ""}).status_code == 422


def test_old_generic_patch_route_no_longer_exists(client):
    db = _db(client)
    _, headers = _admin_headers_with_admin(db)
    owner = _make_user(db, name="Legacy Owner", email="legacy-owner-p4@example.com", phone="9400000052", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Legacy Place")

    response = client.patch(f"{RESTAURANTS_URL}/{restaurant.id}", headers=headers, json={"status": "INACTIVE"})
    assert response.status_code == 405


def test_admin_can_suspend_restaurant_and_it_disappears_from_customers(client):
    db = _db(client)
    headers = _admin_headers(db)
    owner = _make_user(db, name="Suspend Owner", email="suspend-owner-p4@example.com", phone="9400000060", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Suspend Me")

    customer = _make_user(db, name="Browsing Cust", email="browsing-cust-p4@example.com", phone="9400000061", role=UserRole.CUSTOMER)
    customer_token = create_access_token(customer.id)
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    visible_before = client.get("/api/v1/customer/restaurants", headers=customer_headers)
    assert any(r["id"] == str(restaurant.id) for r in visible_before.json())

    suspend = client.post(f"{RESTAURANTS_URL}/{restaurant.id}/suspend", headers=headers, json={"reason": "test"})
    assert suspend.status_code == 200
    assert suspend.json()["approval_status"] == "SUSPENDED"

    visible_after = client.get("/api/v1/customer/restaurants", headers=customer_headers)
    assert not any(r["id"] == str(restaurant.id) for r in visible_after.json())

    detail_after = client.get(f"/api/v1/customer/restaurants/{restaurant.id}", headers=customer_headers)
    assert detail_after.status_code == 404


def test_non_admin_cannot_update_restaurant(client):
    db = _db(client)
    owner = _make_user(db, name="Attacker Owner", email="attacker-owner-p4@example.com", phone="9400000080", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner_id=owner.id, name="Attack Target")
    attacker_token = create_access_token(owner.id)

    response = client.post(
        f"{RESTAURANTS_URL}/{restaurant.id}/deactivate",
        headers={"Authorization": f"Bearer {attacker_token}"},
        json={"reason": "attack"},
    )
    assert response.status_code == 403
