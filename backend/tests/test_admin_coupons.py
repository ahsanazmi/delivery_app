"""Admin Portal — Phase 18: Coupons & Promotions.

Covers the new, complete admin coupon surface at /api/v1/admin/coupons.
The pre-existing /api/v1/coupons admin router (endpoints/coupons.py) is a
separate, untouched surface with its own security-regression test history
— see test_security.py::test_coupon_management_requires_admin_role.
"""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.coupon import Coupon, CouponRedemption, DiscountType
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole

COUPONS_URL = "/api/v1/admin/coupons"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email="admin-p18@example.com", phone="7900000001", role=UserRole.ADMIN)
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_restaurant(db, suffix):
    owner = _make_user(db, name=f"Owner {suffix}", email=f"owner-{suffix}-p18@example.com", phone=f"790000001{suffix}", role=UserRole.RESTAURANT_OWNER)
    restaurant = Restaurant(
        owner_id=owner.id, name=f"Restaurant {suffix}", phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p18@example.com", phone="7900000010", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(COUPONS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(COUPONS_URL).status_code == 401


def test_create_and_get_coupon_with_full_field_set(client):
    db = _db(client)
    headers = _admin_headers(db)
    restaurant = _make_restaurant(db, "1")
    start = datetime.now(UTC).isoformat()
    end = (datetime.now(UTC) + timedelta(days=30)).isoformat()

    create = client.post(
        COUPONS_URL, headers=headers,
        json={
            "code": "welcome10", "discount_type": "percent", "discount_value": "10.00",
            "min_order": "100.00", "max_discount": "50.00", "start_date": start, "end_date": end,
            "usage_limit": 100, "per_customer_limit": 1, "restaurant_id": str(restaurant.id),
        },
    )
    assert create.status_code == 201
    body = create.json()
    assert body["code"] == "WELCOME10"  # uppercased
    assert body["restaurant_name"] == "Restaurant 1"
    assert body["redemption_count"] == 0
    coupon_id = body["id"]

    detail = client.get(f"{COUPONS_URL}/{coupon_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["code"] == "WELCOME10"


def test_create_rejects_duplicate_code(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(COUPONS_URL, headers=headers, json={"code": "DUPE1", "discount_type": "fixed", "discount_value": "20.00"})
    dup = client.post(COUPONS_URL, headers=headers, json={"code": "dupe1", "discount_type": "fixed", "discount_value": "30.00"})
    assert dup.status_code == 409


def test_create_rejects_percentage_over_100(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.post(COUPONS_URL, headers=headers, json={"code": "TOOBIG", "discount_type": "percent", "discount_value": "150"})
    assert response.status_code == 422


def test_create_rejects_end_date_before_start_date(client):
    db = _db(client)
    headers = _admin_headers(db)
    now = datetime.now(UTC)
    response = client.post(
        COUPONS_URL, headers=headers,
        json={
            "code": "BADDATES", "discount_type": "fixed", "discount_value": "10.00",
            "start_date": now.isoformat(), "end_date": (now - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422


def test_create_404_for_nonexistent_restaurant(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.post(
        COUPONS_URL, headers=headers,
        json={"code": "NORESTO", "discount_type": "fixed", "discount_value": "10.00", "restaurant_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


def test_update_coupon_fields(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "UPDATEME", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_id = create.json()["id"]

    update = client.patch(f"{COUPONS_URL}/{coupon_id}", headers=headers, json={"discount_value": "25.00", "is_active": False})
    assert update.status_code == 200
    body = update.json()
    assert Decimal(body["discount_value"]) == Decimal("25.00")
    assert body["is_active"] is False


def test_update_catches_percentage_over_100_even_without_resending_discount_type(client):
    """The gap a schema-only validator would miss: PATCH sends only
    discount_value on an already-PERCENT coupon."""
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "PARTIALPATCH", "discount_type": "percent", "discount_value": "20.00"})
    coupon_id = create.json()["id"]

    update = client.patch(f"{COUPONS_URL}/{coupon_id}", headers=headers, json={"discount_value": "150.00"})
    assert update.status_code == 422

    db.refresh(db.get(Coupon, uuid.UUID(coupon_id)))
    unchanged = client.get(f"{COUPONS_URL}/{coupon_id}", headers=headers)
    assert Decimal(unchanged.json()["discount_value"]) == Decimal("20.00")


def test_update_rejects_duplicate_code(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(COUPONS_URL, headers=headers, json={"code": "TAKEN", "discount_type": "fixed", "discount_value": "10.00"})
    create_two = client.post(COUPONS_URL, headers=headers, json={"code": "FREE", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_two_id = create_two.json()["id"]

    conflict = client.patch(f"{COUPONS_URL}/{coupon_two_id}", headers=headers, json={"code": "TAKEN"})
    assert conflict.status_code == 409


def test_update_requires_at_least_one_field(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "EMPTYPATCH", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_id = create.json()["id"]

    response = client.patch(f"{COUPONS_URL}/{coupon_id}", headers=headers, json={})
    assert response.status_code == 422


def test_update_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.patch(f"{COUPONS_URL}/00000000-0000-0000-0000-000000000000", headers=headers, json={"is_active": False})
    assert response.status_code == 404


def test_delete_coupon_with_no_redemptions(client):
    db = _db(client)
    headers = _admin_headers(db)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "DELETEME", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_id = create.json()["id"]

    response = client.delete(f"{COUPONS_URL}/{coupon_id}", headers=headers)
    assert response.status_code == 204
    assert client.get(f"{COUPONS_URL}/{coupon_id}", headers=headers).status_code == 404


def test_delete_blocked_when_coupon_has_redemptions(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Redeemer", email="redeemer-p18@example.com", phone="7900000020", role=UserRole.CUSTOMER)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "USEDCODE", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_id = create.json()["id"]

    coupon = db.get(Coupon, uuid.UUID(coupon_id))
    db.add(CouponRedemption(coupon_id=coupon.id, user_id=customer.id, order_id=uuid.uuid4()))
    db.commit()

    response = client.delete(f"{COUPONS_URL}/{coupon_id}", headers=headers)
    assert response.status_code == 409

    still_there = client.get(f"{COUPONS_URL}/{coupon_id}", headers=headers)
    assert still_there.status_code == 200


def test_delete_404_for_missing(client):
    db = _db(client)
    headers = _admin_headers(db)
    response = client.delete(f"{COUPONS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_list_search_and_filters(client):
    db = _db(client)
    headers = _admin_headers(db)
    client.post(COUPONS_URL, headers=headers, json={"code": "FINDABLE20", "discount_type": "percent", "discount_value": "20.00"})
    inactive = client.post(COUPONS_URL, headers=headers, json={"code": "INACTIVE30", "discount_type": "fixed", "discount_value": "30.00"})
    client.patch(f"{COUPONS_URL}/{inactive.json()['id']}", headers=headers, json={"is_active": False})

    by_search = client.get(COUPONS_URL, headers=headers, params={"search": "FINDABLE"})
    assert [c["code"] for c in by_search.json()["items"]] == ["FINDABLE20"]

    by_type = client.get(COUPONS_URL, headers=headers, params={"discount_type": "fixed"})
    codes = [c["code"] for c in by_type.json()["items"]]
    assert "INACTIVE30" in codes
    assert "FINDABLE20" not in codes

    by_active = client.get(COUPONS_URL, headers=headers, params={"is_active": "false"})
    codes = [c["code"] for c in by_active.json()["items"]]
    assert "INACTIVE30" in codes
    assert "FINDABLE20" not in codes


def test_list_shows_redemption_count(client):
    db = _db(client)
    headers = _admin_headers(db)
    customer = _make_user(db, name="Redeemer Two", email="redeemer2-p18@example.com", phone="7900000030", role=UserRole.CUSTOMER)
    create = client.post(COUPONS_URL, headers=headers, json={"code": "COUNTME", "discount_type": "fixed", "discount_value": "10.00"})
    coupon_id = create.json()["id"]

    import uuid
    coupon = db.get(Coupon, uuid.UUID(coupon_id))
    db.add(CouponRedemption(coupon_id=coupon.id, user_id=customer.id, order_id=uuid.uuid4()))
    db.add(CouponRedemption(coupon_id=coupon.id, user_id=customer.id, order_id=uuid.uuid4()))
    db.commit()

    response = client.get(COUPONS_URL, headers=headers, params={"search": "COUNTME"})
    assert response.json()["items"][0]["redemption_count"] == 2


def test_pagination(client):
    db = _db(client)
    headers = _admin_headers(db)
    for i in range(3):
        client.post(COUPONS_URL, headers=headers, json={"code": f"PAGE{i}", "discount_type": "fixed", "discount_value": "10.00"})

    response = client.get(COUPONS_URL, headers=headers, params={"page": 1, "limit": 2})
    body = response.json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2


def test_legacy_admin_coupon_endpoint_at_bare_path_still_works_unchanged(client):
    """Phase 18 built a new, complete surface at /admin/coupons without
    touching the pre-existing /api/v1/coupons admin router — this proves
    that older surface is still intact and still admin-only."""
    db = _db(client)
    headers = _admin_headers(db)
    response = client.post("/api/v1/coupons", headers=headers, json={"code": "LEGACY1", "discount_type": "percent", "discount_value": "5"})
    assert response.status_code == 201
