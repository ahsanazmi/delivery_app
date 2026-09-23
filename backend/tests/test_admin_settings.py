"""Admin Portal — Phase 22: Admin Settings.

Covers the settings CRUD surface itself, plus the three concrete places
this phase's values actually get consumed: a new restaurant's fallback
delivery fee/minimum order, the platform-wide notification kill switch,
and maintenance mode blocking checkout. "Default commission" is
deliberately absent here — Phase 17's CommissionRule already owns it.
"""

import uuid
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.address import Address
from app.models.admin_audit_log import AdminAuditLog
from app.models.notification import Notification
from app.models.product import Product
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.schemas.restaurant import RestaurantCreate
from app.services.cart import add_item, create_cart_for_user
from app.services.checkout import get_checkout_preview, validate_checkout
from app.services.notifications import broadcast_promotion
from app.services.restaurants import create_restaurant

SETTINGS_URL = "/api/v1/admin/settings"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin(db, suffix="p22"):
    admin = _make_user(db, name="Admin", email=f"admin-{suffix}-{uuid.uuid4().hex[:8]}@example.com", phone=f"74{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_settings_endpoints_require_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p22@example.com", phone="7400000001", role=UserRole.CUSTOMER)
    headers = {"Authorization": f"Bearer {create_access_token(customer.id)}"}

    assert client.get(SETTINGS_URL, headers=headers).status_code == 403
    assert client.get(SETTINGS_URL).status_code == 401
    assert client.patch(SETTINGS_URL, headers=headers, json={"platform_name": "x"}).status_code == 403
    assert client.patch(SETTINGS_URL, json={"platform_name": "x"}).status_code == 401


def test_get_settings_lazily_creates_defaults(client):
    db = _db(client)
    _, headers = _admin(db)

    response = client.get(SETTINGS_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["platform_name"] == "Say Hi Chai"
    assert Decimal(body["default_delivery_fee"]) == Decimal("0.00")
    assert Decimal(body["default_minimum_order"]) == Decimal("0.00")
    assert body["notifications_enabled"] is True
    assert body["maintenance_mode"] is False
    assert body["support_email"] is None


def test_update_rejects_empty_payload(client):
    db = _db(client)
    _, headers = _admin(db)
    assert client.patch(SETTINGS_URL, headers=headers, json={}).status_code == 422


def test_update_changes_fields_and_writes_an_audit_log_entry(client):
    db = _db(client)
    admin, headers = _admin(db)

    response = client.patch(
        SETTINGS_URL, headers=headers,
        json={
            "platform_name": "Chai Express", "support_email": "help@chai.example", "maintenance_mode": True,
            "reason": "Rebranding for the festival promo",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["platform_name"] == "Chai Express"
    assert body["support_email"] == "help@chai.example"
    assert body["maintenance_mode"] is True
    # Untouched field keeps its previous value.
    assert body["notifications_enabled"] is True

    entry = db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "platform_settings").one()
    assert entry.admin_id == admin.id
    assert entry.action == "settings.update"
    assert entry.reason == "Rebranding for the festival promo"


def test_update_with_no_actual_changes_writes_no_audit_log_entry(client):
    db = _db(client)
    _, headers = _admin(db)
    client.get(SETTINGS_URL, headers=headers)

    response = client.patch(SETTINGS_URL, headers=headers, json={"platform_name": "Say Hi Chai"})
    assert response.status_code == 200
    assert db.query(AdminAuditLog).filter(AdminAuditLog.target_type == "platform_settings").count() == 0


def test_new_restaurant_falls_back_to_platform_defaults_when_unspecified(client):
    db = _db(client)
    admin, headers = _admin(db)
    client.patch(SETTINGS_URL, headers=headers, json={"default_delivery_fee": "35.00", "default_minimum_order": "150.00"})

    owner = _make_user(db, name="Owner", email="owner-p22@example.com", phone="7400000010", role=UserRole.RESTAURANT_OWNER)
    restaurant = create_restaurant(
        db, RestaurantCreate(name="Fallback R", phone="9876500000", address="123 Some Street", latitude=Decimal("12.97"), longitude=Decimal("77.59"), owner_id=owner.id),
        actor=admin,
    )
    assert restaurant.delivery_fee == Decimal("35.00")
    assert restaurant.minimum_order == Decimal("150.00")


def test_new_restaurant_explicit_values_are_not_overridden_by_platform_defaults(client):
    db = _db(client)
    admin, headers = _admin(db)
    client.patch(SETTINGS_URL, headers=headers, json={"default_delivery_fee": "35.00"})

    owner = _make_user(db, name="Owner2", email="owner-p22-b@example.com", phone="7400000011", role=UserRole.RESTAURANT_OWNER)
    restaurant = create_restaurant(
        db, RestaurantCreate(
            name="Explicit R", phone="9876500001", address="123 Some Street", latitude=Decimal("12.97"),
            longitude=Decimal("77.59"), owner_id=owner.id, delivery_fee=Decimal("99.00"),
        ),
        actor=admin,
    )
    assert restaurant.delivery_fee == Decimal("99.00")


def test_notifications_disabled_suppresses_broadcast(client):
    db = _db(client)
    _, headers = _admin(db)
    client.patch(SETTINGS_URL, headers=headers, json={"notifications_enabled": False})

    customer = _make_user(db, name="Cust", email="cust-p22@example.com", phone="7400000020", role=UserRole.CUSTOMER)
    notified = broadcast_promotion(db, "Sale!", "50% off today.")
    assert notified == 0
    assert db.query(Notification).filter(Notification.user_id == customer.id).count() == 0

    client.patch(SETTINGS_URL, headers=headers, json={"notifications_enabled": True})
    notified_again = broadcast_promotion(db, "Sale!", "50% off today.")
    assert notified_again == 0  # no push token registered, but the row should still be created
    assert db.query(Notification).filter(Notification.user_id == customer.id).count() == 1


def test_maintenance_mode_blocks_checkout(client):
    db = _db(client)
    _, headers = _admin(db)

    owner = _make_user(db, name="Owner3", email="owner-p22-c@example.com", phone="7400000030", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name="Maint R", phone="9876500002", address="Addr", latitude=Decimal("12.97"),
        longitude=Decimal("77.59"), minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"), is_open=True,
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)

    product = Product(restaurant_id=restaurant.id, name="Chai", price=Decimal("50.00"), is_available=True)
    db.add(product)
    db.commit()
    db.refresh(product)

    customer = _make_user(db, name="Cust2", email="cust-p22-b@example.com", phone="7400000031", role=UserRole.CUSTOMER)
    address = Address(user_id=customer.id, label="Home", recipient_name="Cust2", phone="7400000031", address_line="1 Main St", city="Town", state="Karnataka", postal_code="123456", latitude=Decimal("12.97"), longitude=Decimal("77.59"), is_default=True)
    db.add(address)
    db.commit()
    db.refresh(address)

    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)

    preview_before = get_checkout_preview(db, customer)
    assert preview_before["issues"] == []

    client.patch(SETTINGS_URL, headers=headers, json={"maintenance_mode": True})

    preview_after = get_checkout_preview(db, customer)
    assert any("maintenance" in issue.lower() for issue in preview_after["issues"])

    validation = validate_checkout(db, customer, address.id)
    assert validation["valid"] is False
    assert any("maintenance" in issue.lower() for issue in validation["issues"])
