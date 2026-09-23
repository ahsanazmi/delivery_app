"""Admin Portal — Phase 25: Admin Security Audit.

A dedicated, cross-cutting pass over every /api/v1/admin/* route built in
Phases 1-24, following the same audit style as
tests/test_restaurant_security_audit.py and tests/test_rider_security_audit.py.

Three things this file proves, together, as security properties rather
than incidental feature behavior:

1. Every single registered admin route (enumerated dynamically from the
   app's own OpenAPI schema, not a hand-maintained list that could go
   stale) rejects CUSTOMER/RIDER/RESTAURANT_OWNER with 403 and an
   unauthenticated request with 401 — and admin can actually get through.
2. IDOR resistance on the five named detail endpoints: a non-admin can't
   read another user's admin-view record by guessing its id, even when
   the id is their *own* — the role check gates first, never a resource-
   ownership check that a same-role caller could satisfy.
3. Each of the six explicit "admin must not be able to" guarantees holds,
   verified either by static schema introspection (proving the capability
   was never wired up, not just that today's UI doesn't expose it) or a
   live HTTP probe. All six were already true by construction — this
   audit found no gap requiring a code fix — see the phase's own
   completion report for the reasoning behind each.
"""

import re
import uuid
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.rider_settlement import RiderSettlement, SettlementType
from app.models.user import User, UserRole
from app.schemas import admin as admin_schemas

_UUID_RE = re.compile(r"\{[^}]+\}")
_FORBIDDEN_FIELD_NAMES = {
    "password", "password_hash", "hashed_password",
    "razorpay_key_id", "razorpay_key_secret", "razorpay_webhook_secret",
    "jwt_secret_key", "refresh_token",
}


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role, password="Passw0rd!"):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_restaurant(db, owner_id, name="Audit Restaurant"):
    restaurant = Restaurant(
        owner_id=owner_id, name=name, phone="9876500000", address="Addr",
        latitude=Decimal("12.97"), longitude=Decimal("77.59"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("20.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _make_order(db, *, customer, restaurant, status=OrderStatus.PLACED, total=Decimal("100.00")):
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=total, delivery_fee=Decimal("20.00"), total=total + Decimal("20.00"),
        payment_method="cod", address_line="1 Main St", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


# --------------------------------------------------------------------
# 1. Every admin route rejects every non-admin role and unauthenticated
# --------------------------------------------------------------------


def _all_admin_routes(client):
    schema = client.app.openapi()
    routes = []
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1/admin"):
            continue
        for method in methods:
            if method.upper() in ("GET", "POST", "PATCH", "PUT", "DELETE"):
                routes.append((method.upper(), path))
    return routes


def _concrete_path(path: str) -> str:
    return _UUID_RE.sub(lambda _: str(uuid.uuid4()), path)


def test_every_admin_route_enumeration_is_non_trivial(client):
    """Sanity check on the audit mechanism itself — if this ever drops to
    a handful of routes, the OpenAPI-based enumeration below has broken
    silently and the whole audit would be vacuously passing."""
    routes = _all_admin_routes(client)
    assert len(routes) >= 65


def test_every_admin_route_blocks_non_admin_roles_and_unauthenticated(client):
    db = _db(client)
    customer = _make_user(db, name="Audit Customer", email="audit-customer-p25@example.com", phone="7500000001", role=UserRole.CUSTOMER)
    rider = _make_user(db, name="Audit Rider", email="audit-rider-p25@example.com", phone="7500000002", role=UserRole.RIDER)
    owner = _make_user(db, name="Audit Owner", email="audit-owner-p25@example.com", phone="7500000003", role=UserRole.RESTAURANT_OWNER)

    role_tokens = {
        "CUSTOMER": create_access_token(customer.id),
        "RIDER": create_access_token(rider.id),
        "RESTAURANT_OWNER": create_access_token(owner.id),
    }

    routes = _all_admin_routes(client)
    role_failures = []
    unauth_failures = []

    for method, path in routes:
        concrete = _concrete_path(path)
        body = {} if method in ("POST", "PATCH", "PUT") else None

        for role, token in role_tokens.items():
            response = client.request(method, concrete, headers={"Authorization": f"Bearer {token}"}, json=body)
            if response.status_code != 403:
                role_failures.append((role, method, path, response.status_code))

        response = client.request(method, concrete, json=body)
        if response.status_code != 401:
            unauth_failures.append((method, path, response.status_code))

    assert not role_failures, f"Non-admin role(s) were not blocked (expected 403): {role_failures}"
    assert not unauth_failures, f"Unauthenticated request(s) were not blocked (expected 401): {unauth_failures}"


def test_admin_role_actually_gets_through_on_list_endpoints(client):
    """The mirror image of the test above — proves require_admin isn't
    accidentally blocking everyone, only non-admins."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin", email="audit-admin-p25@example.com", phone="7500000004", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    for path in (
        "/api/v1/admin/dashboard", "/api/v1/admin/customers", "/api/v1/admin/restaurants",
        "/api/v1/admin/restaurant-owners", "/api/v1/admin/riders", "/api/v1/admin/orders",
        "/api/v1/admin/payments", "/api/v1/admin/cod", "/api/v1/admin/audit-logs",
        "/api/v1/admin/settings", "/api/v1/admin/notifications",
    ):
        response = client.get(path, headers=headers)
        assert response.status_code == 200, (path, response.status_code)


# --------------------------------------------------------------------
# 2. IDOR resistance on the five named detail endpoints
# --------------------------------------------------------------------


@pytest.mark.parametrize(
    "url_template,make_target_id",
    [
        ("/api/v1/admin/customers/{id}", "customer"),
        ("/api/v1/admin/restaurants/{id}", "restaurant"),
        ("/api/v1/admin/riders/{id}", "rider"),
        ("/api/v1/admin/orders/{id}", "order"),
        ("/api/v1/admin/payments/{id}", "payment"),
    ],
)
def test_non_admin_cannot_read_admin_detail_view_even_of_their_own_record(client, url_template, make_target_id):
    """The IDOR case that actually matters here: these are admin-wide
    views with no per-user scoping at all, so the only thing standing
    between a non-admin and someone else's record is the role check.
    Proves the role check gates even when the caller passes *their own*
    id — there is no "well it's their own data" bypass anywhere."""
    db = _db(client)
    customer = _make_user(db, name="IDOR Customer", email="idor-customer-p25@example.com", phone="7500000010", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="IDOR Owner", email="idor-owner-p25@example.com", phone="7500000011", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner.id, "IDOR Restaurant")
    rider = _make_user(db, name="IDOR Rider", email="idor-rider-p25@example.com", phone="7500000012", role=UserRole.RIDER)
    order = _make_order(db, customer=customer, restaurant=restaurant)
    payment = Payment(order_id=order.id, user_id=customer.id, provider=PaymentProvider.COD, amount=order.total)
    db.add(payment)
    db.commit()
    db.refresh(payment)

    target_ids = {
        "customer": customer.id, "restaurant": restaurant.id, "rider": rider.id,
        "order": order.id, "payment": payment.id,
    }
    own_id_by_role = {"customer": customer.id, "restaurant": owner.id, "rider": rider.id}

    attacker_tokens = {
        "customer": create_access_token(customer.id),
        "owner": create_access_token(owner.id),
        "rider": create_access_token(rider.id),
    }

    url = url_template.format(id=target_ids[make_target_id])
    for attacker_role, token in attacker_tokens.items():
        response = client.get(url, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403, (attacker_role, url, response.status_code)

    # Explicitly re-check the strongest case: the caller's own id, where
    # they legitimately own the underlying record (their own customer/
    # owner/rider row) — still 403, never "it's your own data so it's fine".
    own_id = own_id_by_role.get(make_target_id)
    if own_id is not None:
        self_url = url_template.format(id=own_id)
        self_token = attacker_tokens["customer" if make_target_id == "customer" else ("owner" if make_target_id == "restaurant" else "rider")]
        response = client.get(self_url, headers={"Authorization": f"Bearer {self_token}"})
        assert response.status_code == 403


def test_admin_can_read_any_record_and_gets_404_not_a_crash_for_missing_ones(client):
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 2", email="audit-admin2-p25@example.com", phone="7500000020", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Readable Customer", email="readable-customer-p25@example.com", phone="7500000021", role=UserRole.CUSTOMER)

    assert client.get(f"/api/v1/admin/customers/{customer.id}", headers=headers).status_code == 200
    assert client.get(f"/api/v1/admin/customers/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/admin/orders/{uuid.uuid4()}", headers=headers).status_code == 404
    assert client.get(f"/api/v1/admin/payments/{uuid.uuid4()}", headers=headers).status_code == 404


# --------------------------------------------------------------------
# 3. "Admin must not be able to" — six explicit guarantees
# --------------------------------------------------------------------


def _all_admin_schema_field_names() -> set[str]:
    names: set[str] = set()
    for attr_name in dir(admin_schemas):
        attr = getattr(admin_schemas, attr_name)
        if isinstance(attr, type) and hasattr(attr, "model_fields"):
            names.update(attr.model_fields.keys())
    return names


def test_no_admin_schema_ever_declares_a_password_or_secret_field(client):
    """(1) Change password hashes directly, (2) Access authentication
    secrets. If a password/secret field was ever wired into a request or
    response schema, it would show up here regardless of whether any
    current UI happens to use it."""
    declared_fields = _all_admin_schema_field_names()
    leaked = declared_fields & _FORBIDDEN_FIELD_NAMES
    assert not leaked, f"Forbidden field(s) declared on an admin schema: {leaked}"


def test_smuggled_password_field_in_suspend_request_is_ignored(client):
    """(1) Change password hashes directly — a live probe alongside the
    static check above: even if an attacker (an admin, here) sends a
    password_hash in the body of an action whose schema doesn't declare
    one, pydantic drops the unknown field before it ever reaches the ORM."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 3", email="audit-admin3-p25@example.com", phone="7500000030", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Smuggle Target", email="smuggle-target-p25@example.com", phone="7500000031", role=UserRole.CUSTOMER)
    original_hash = customer.password_hash

    response = client.post(
        f"/api/v1/admin/customers/{customer.id}/suspend",
        headers=headers,
        json={"reason": "test", "password_hash": "$2b$12$attacker-controlled-hash", "password": "hunter2"},
    )
    assert response.status_code == 200

    db.refresh(customer)
    assert customer.password_hash == original_hash


def test_no_admin_endpoint_response_ever_contains_a_password_hash_or_provider_secret(client):
    """(2) Access authentication secrets — greps the raw response text of
    every detail/list view this phase's IDOR section touches, the same
    "grep the wire format, not just the schema" technique Phase 13 used
    to prove razorpay_signature never leaks."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 4", email="audit-admin4-p25@example.com", phone="7500000040", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Grep Customer", email="grep-customer-p25@example.com", phone="7500000041", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Grep Owner", email="grep-owner-p25@example.com", phone="7500000042", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner.id, "Grep Restaurant")
    rider = _make_user(db, name="Grep Rider", email="grep-rider-p25@example.com", phone="7500000043", role=UserRole.RIDER)
    order = _make_order(db, customer=customer, restaurant=restaurant)
    payment = Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
        amount=order.total, razorpay_signature="super-secret-signature-value",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    for url in (
        f"/api/v1/admin/customers/{customer.id}", "/api/v1/admin/customers",
        f"/api/v1/admin/restaurant-owners/{owner.id}", "/api/v1/admin/restaurant-owners",
        f"/api/v1/admin/riders/{rider.id}", "/api/v1/admin/riders",
        f"/api/v1/admin/payments/{payment.id}", "/api/v1/admin/payments",
        "/api/v1/admin/settings",
    ):
        raw = client.get(url, headers=headers).text
        assert customer.password_hash not in raw
        assert owner.password_hash not in raw
        assert rider.password_hash not in raw
        assert "super-secret-signature-value" not in raw
        assert "razorpay_signature" not in raw


def test_no_generic_field_mutation_route_exists(client):
    """(3) Modify database directly through an API. Every generic
    accept-any-field PATCH this platform ever had was removed in earlier
    phases (Phase 11 for orders, Phase 23 for customer/owner/restaurant
    status) — this re-confirms none of them silently came back, and that
    no other resource has one either (categories/coupons/service-areas
    only ever expose their own narrow, explicitly-typed update schema —
    see the static schema check below for what fields those schemas
    actually accept)."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 5", email="audit-admin5-p25@example.com", phone="7500000050", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Generic Target", email="generic-target-p25@example.com", phone="7500000051", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Generic Owner", email="generic-owner-p25@example.com", phone="7500000052", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner.id, "Generic Restaurant")

    assert client.patch(f"/api/v1/admin/customers/{customer.id}", headers=headers, json={"status": "SUSPENDED"}).status_code == 405
    assert client.patch(f"/api/v1/admin/restaurant-owners/{owner.id}", headers=headers, json={"status": "SUSPENDED"}).status_code == 405
    assert client.patch(f"/api/v1/admin/restaurants/{restaurant.id}", headers=headers, json={"status": "INACTIVE"}).status_code == 405


def test_cod_settlement_cannot_exceed_actual_outstanding_balance(client):
    """(4) Create arbitrary financial transactions — the one place admin
    code writes a new financial ledger row at all (RiderSettlement,
    Phase 14) refuses any amount beyond what's genuinely outstanding, so
    an admin can never conjure money into the ledger that was never
    actually collected."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 6", email="audit-admin6-p25@example.com", phone="7500000060", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    rider = _make_user(db, name="COD Rider", email="cod-rider-p25@example.com", phone="7500000061", role=UserRole.RIDER)
    customer = _make_user(db, name="COD Customer", email="cod-customer-p25@example.com", phone="7500000062", role=UserRole.CUSTOMER)
    restaurant = _make_restaurant(db, _make_user(db, name="COD Owner", email="cod-owner-p25@example.com", phone="7500000063", role=UserRole.RESTAURANT_OWNER).id)
    order = _make_order(db, customer=customer, restaurant=restaurant)
    db.add(Payment(
        order_id=order.id, user_id=customer.id, provider=PaymentProvider.COD,
        payment_status=PaymentStatus.PAID, amount=Decimal("100.00"), collected_by_rider_id=rider.id,
    ))
    db.commit()

    response = client.post(f"/api/v1/admin/cod/{rider.id}/settle", headers=headers, json={"amount": "999999.00"})
    assert response.status_code == 409

    assert db.query(RiderSettlement).filter(RiderSettlement.rider_id == rider.id).count() == 0


def test_order_intervention_never_touches_financial_fields_even_if_smuggled(client):
    """(5) Change historical order totals. admin_cancel_order/
    admin_reassign_rider only ever accept a `reason` (and, for reassign,
    a `new_rider_id`) — proves a smuggled `total`/`subtotal`/
    `commission_amount` in the request body is silently dropped, never
    applied to the order."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 7", email="audit-admin7-p25@example.com", phone="7500000070", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Financial Customer", email="financial-customer-p25@example.com", phone="7500000071", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Financial Owner", email="financial-owner-p25@example.com", phone="7500000072", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner.id, "Financial Restaurant")
    order = _make_order(db, customer=customer, restaurant=restaurant, total=Decimal("100.00"))
    original_total = order.total
    original_subtotal = order.subtotal

    response = client.post(
        f"/api/v1/admin/orders/{order.id}/cancel",
        headers=headers,
        json={"reason": "test", "total": "1.00", "subtotal": "1.00", "commission_amount": "500.00"},
    )
    assert response.status_code == 200

    db.refresh(order)
    assert order.total == original_total
    assert order.subtotal == original_subtotal


def test_changing_commission_rule_never_alters_an_already_placed_orders_snapshot(client):
    """(5) Change historical order totals — the commission-specific angle
    Phase 17 already proved in its own test file; restated here as part
    of this phase's consolidated checklist, per this project's own
    established audit convention (see test_rider_security_audit.py's own
    docstring)."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 8", email="audit-admin8-p25@example.com", phone="7500000080", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}
    customer = _make_user(db, name="Snapshot Customer", email="snapshot-customer-p25@example.com", phone="7500000081", role=UserRole.CUSTOMER)
    owner = _make_user(db, name="Snapshot Owner", email="snapshot-owner-p25@example.com", phone="7500000082", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner.id, "Snapshot Restaurant")
    order = _make_order(db, customer=customer, restaurant=restaurant, total=Decimal("200.00"))
    order.commission_type = "PERCENTAGE"
    order.commission_rate = Decimal("10")
    order.commission_amount = Decimal("20.00")
    db.commit()

    response = client.patch(
        "/api/v1/admin/commissions", headers=headers,
        json={"default": {"commission_type": "FIXED", "value": "999.00"}},
    )
    assert response.status_code == 200

    db.refresh(order)
    assert order.commission_amount == Decimal("20.00")


def test_no_admin_schema_or_endpoint_ever_touches_payment_provider_credentials(client):
    """(6) Manipulate payment-provider credentials. Static check: no
    admin schema field name is Razorpay-credential-shaped (see the
    forbidden-field-names check above, which already covers this) — this
    test additionally confirms the live settings endpoint, the only admin
    surface that could plausibly hold "platform configuration," accepts
    no such field even when one is smuggled in."""
    db = _db(client)
    admin = _make_user(db, name="Audit Admin 9", email="audit-admin9-p25@example.com", phone="7500000090", role=UserRole.ADMIN)
    headers = {"Authorization": f"Bearer {create_access_token(admin.id)}"}

    response = client.patch(
        "/api/v1/admin/settings", headers=headers,
        json={"platform_name": "Still Say Hi Chai", "razorpay_key_secret": "attacker-supplied-secret"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "razorpay_key_secret" not in body
    assert "razorpay" not in response.text.lower()
