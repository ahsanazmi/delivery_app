"""Phase 22 — dedicated security pass.

Covers cross-customer authorization boundaries, role boundaries on
admin/rider-only routes, JWT validation edge cases, password hashing, and
regression tests for the vulnerabilities found and fixed during this audit
(unauthenticated coupon management, client-trusted payment amount, and the
Razorpay webhook signature bypass).
"""

import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Address, Product, Restaurant, User, UserRole
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com", phone="9000000000"):
    user = User(name="Customer", email=email, phone=phone, password_hash=hash_password("Passw0rd!"), role=UserRole.CUSTOMER)
    db.add(user)
    db.commit()
    return user


def _restaurant(db):
    owner = User(name="Owner", email="owner@example.com", password_hash="x", role=UserRole.RESTAURANT_OWNER)
    db.add(owner)
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id,
        name="Chai House",
        phone="9876543210",
        address="Main Road",
        latitude=Decimal("12.1"),
        longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"),
        delivery_fee=Decimal("0.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _http_setup():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return engine


def _teardown(engine):
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


# ---------------------------------------------------------------------------
# Cross-customer authorization
# ---------------------------------------------------------------------------


def test_customer_cannot_access_another_customers_address_over_http():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _customer(seed, email="owner@example.com", phone="9111111111")
            other = _customer(seed, email="other@example.com", phone="9222222222")
            address = create_address(seed, owner.id, {
                "label": "Home",
                "recipient_name": "Owner",
                "phone": "9999999999",
                "address_line": "1 Main St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560001",
            })
            address_id = address.id
            other_token = create_access_token(other.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {other_token}"}
            get_resp = client.get(f"/api/v1/customer/addresses/{address_id}", headers=headers)
            assert get_resp.status_code == 404

            patch_resp = client.patch(
                f"/api/v1/customer/addresses/{address_id}", headers=headers, json={"label": "Hacked"}
            )
            assert patch_resp.status_code == 404

            delete_resp = client.delete(f"/api/v1/customer/addresses/{address_id}", headers=headers)
            assert delete_resp.status_code == 404
    finally:
        _teardown(engine)


def test_customer_cannot_access_another_customers_order_over_http():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            owner = _customer(seed, email="order-owner@example.com", phone="9111111111")
            other = _customer(seed, email="other@example.com", phone="9222222222")
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, owner.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, owner.id, {
                "label": "Home",
                "recipient_name": "Owner",
                "phone": "9999999999",
                "address_line": "1 Main St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560001",
            })
            order = create_order(seed, owner, address.id)
            order_id = order.id
            other_token = create_access_token(other.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {other_token}"}
            get_resp = client.get(f"/api/v1/customer/orders/{order_id}", headers=headers)
            assert get_resp.status_code == 404

            cancel_resp = client.post(f"/api/v1/customer/orders/{order_id}/cancel", headers=headers)
            assert cancel_resp.status_code == 404

            reorder_resp = client.post(f"/api/v1/customer/orders/{order_id}/reorder", headers=headers)
            assert reorder_resp.status_code == 404

            tracking_resp = client.get(f"/api/v1/customer/orders/{order_id}/tracking", headers=headers)
            assert tracking_resp.status_code == 404

            payment_resp = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)
            assert payment_resp.status_code == 404
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Role boundaries — a customer must never reach admin/rider-only routes
# ---------------------------------------------------------------------------


def test_customer_cannot_access_admin_or_rider_routes_over_http():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            assert client.get("/api/v1/admin/dashboard", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/customers", headers=headers).status_code == 403
            assert client.get("/api/v1/admin/riders", headers=headers).status_code == 403
            assert client.post(
                "/api/v1/admin/notifications/broadcast", headers=headers, json={"title": "x", "body": "y"}
            ).status_code == 403

            assert client.get("/api/v1/rider/orders", headers=headers).status_code == 403
            assert client.patch(
                "/api/v1/rider/location", headers=headers, json={"latitude": "1", "longitude": "1"}
            ).status_code == 403
    finally:
        _teardown(engine)


def test_unauthenticated_request_is_rejected_not_defaulted_to_a_role():
    engine = _http_setup()
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/admin/dashboard").status_code == 401
            assert client.get("/api/v1/customer/orders").status_code == 401
            assert client.get("/api/v1/rider/orders").status_code == 401
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Regression tests for vulnerabilities found and fixed during this audit
# ---------------------------------------------------------------------------


def test_coupon_management_requires_admin_role():
    """Previously this whole router had zero auth — anyone could create
    arbitrary discount coupons with no login at all."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            # Fully unauthenticated — must be rejected outright.
            unauth = client.post(
                "/api/v1/coupons",
                json={"code": "FREE100", "discount_type": "percent", "discount_value": "100"},
            )
            assert unauth.status_code == 401

            # Authenticated as a plain customer — still not allowed.
            headers = {"Authorization": f"Bearer {token}"}
            forbidden = client.post(
                "/api/v1/coupons",
                headers=headers,
                json={"code": "FREE100", "discount_type": "percent", "discount_value": "100"},
            )
            assert forbidden.status_code == 403
            assert client.get("/api/v1/coupons", headers=headers).status_code == 403
    finally:
        _teardown(engine)


def test_payment_amount_is_never_taken_from_the_client():
    """Previously PaymentCreate.amount was accepted verbatim from the client
    and written straight into the Payment row, regardless of the order's real
    total."""
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("500.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home",
                "recipient_name": "Customer",
                "phone": "9999999999",
                "address_line": "1 Main St",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560001",
            })
            order = create_order(seed, customer, address.id)
            order_id = order.id
            order_total = order.total
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            # Try to sneak an attacker-chosen amount through — the schema no
            # longer even accepts the field, but confirm the server-derived
            # amount is correct regardless of what's in the request body.
            # method="cod" here (not "razorpay") deliberately — this test's
            # own point is amount trust, not the Razorpay path, and COD
            # payment creation needs no live provider/network access.
            response = client.post(
                "/api/v1/payments/create",
                headers=headers,
                json={"order_id": str(order_id), "amount": "0.01", "method": "cod"},
            )
            assert response.status_code == 201
            assert Decimal(response.json()["amount"]) == order_total
    finally:
        _teardown(engine)


def test_calling_create_payment_twice_never_creates_two_payment_rows():
    """Integration Phase 12 — POST /api/v1/payments previously had no
    idempotency check at all: calling it twice for the same order created
    two separate Payment rows unconditionally. Now backed by
    uq_payments_order_id (see app/models/payment.py) and an explicit
    find-existing-first check, a second call must return the same payment
    id, and the database must still hold exactly one row for this order."""
    from app.models.payment import Payment

    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("500.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
                "address_line": "1 Main St", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            })
            order = create_order(seed, customer, address.id)
            order_id = order.id
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}
            first = client.post("/api/v1/payments/create", headers=headers, json={"order_id": str(order_id), "method": "cod"})
            second = client.post("/api/v1/payments/create", headers=headers, json={"order_id": str(order_id), "method": "cod"})
            assert first.status_code == 201
            assert second.status_code == 201
            assert first.json()["id"] == second.json()["id"]

        with Session(engine) as verify:
            count = verify.query(Payment).filter(Payment.order_id == order_id).count()
            assert count == 1
    finally:
        _teardown(engine)


def test_payments_table_rejects_a_second_row_for_the_same_order_at_the_database_level():
    """The uq_payments_order_id constraint itself — a defense-in-depth
    backstop below any application-level idempotency check, for any future
    code path that might try to insert a second payment for one order."""
    from sqlalchemy.exc import IntegrityError

    from app.models.payment import Payment

    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("500.00"))
            seed.add(product)
            seed.commit()
            cart = create_cart_for_user(seed, customer.id)
            add_item(seed, cart, product.id, 1)
            address = create_address(seed, customer.id, {
                "label": "Home", "recipient_name": "Customer", "phone": "9999999999",
                "address_line": "1 Main St", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
            })
            order = create_order(seed, customer, address.id)

            first = Payment(user_id=customer.id, order_id=order.id, amount=order.total)
            seed.add(first)
            seed.commit()

            second = Payment(user_id=customer.id, order_id=order.id, amount=order.total)
            seed.add(second)
            with pytest.raises(IntegrityError):
                seed.commit()
    finally:
        _teardown(engine)


def test_razorpay_webhook_rejects_forged_signature():
    engine = _http_setup()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/payments/webhooks/razorpay",
                headers={"x-razorpay-signature": "totally-fabricated"},
                content=b'{"event": "payment.authorized"}',
            )
            # No RAZORPAY_WEBHOOK_SECRET is configured in this environment, so
            # the honest answer is "can't verify" (503) rather than accepting
            # an unverified payload (which is what happened before this fix).
            assert response.status_code == 503
    finally:
        _teardown(engine)


def test_razorpay_webhook_requires_a_signature_header():
    engine = _http_setup()
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/payments/webhooks/razorpay", content=b"{}")
            assert response.status_code == 400
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# JWT validation
# ---------------------------------------------------------------------------


def test_tampered_token_signature_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        tampered = token[:-4] + "abcd"
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/customer/orders", headers={"Authorization": f"Bearer {tampered}"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_expired_token_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            customer_id = customer.id

        expired = jwt.encode(
            {"sub": str(customer_id), "type": "access", "exp": datetime.now(UTC) - timedelta(minutes=1)},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/customer/orders", headers={"Authorization": f"Bearer {expired}"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_refresh_token_cannot_be_used_as_an_access_token():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            customer_id = customer.id

        refresh_shaped_token = jwt.encode(
            {"sub": str(customer_id), "type": "refresh", "exp": datetime.now(UTC) + timedelta(days=1)},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        with TestClient(app) as client:
            response = client.get(
                "/api/v1/customer/orders", headers={"Authorization": f"Bearer {refresh_shaped_token}"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


def test_deactivated_user_token_is_rejected():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            customer.is_active = False
            seed.commit()
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/customer/orders", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 401
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Password hashing and sensitive data exposure
# ---------------------------------------------------------------------------


def test_password_is_hashed_not_stored_or_returned_in_plaintext(db):
    user = _customer(db)
    user.password_hash = hash_password("correct-horse-battery-staple")
    db.commit()

    assert user.password_hash != "correct-horse-battery-staple"
    assert user.password_hash.startswith("$argon2")
    assert verify_password("correct-horse-battery-staple", user.password_hash) is True
    assert verify_password("wrong-password", user.password_hash) is False


def test_user_read_schema_never_exposes_password_hash():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            token = create_access_token(customer.id)

        with TestClient(app) as client:
            response = client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
            assert "password_hash" not in response.text
            assert "password" not in response.json()
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Rate limiting readiness
# ---------------------------------------------------------------------------


def test_login_is_rate_limited_after_repeated_attempts():
    engine = _http_setup()
    try:
        with Session(engine) as seed:
            _customer(seed, email="ratelimited@example.com", phone="9333333333")

        with TestClient(app) as client:
            payload = {"email": "ratelimited@example.com", "password": "wrong-password"}
            statuses = [client.post("/api/v1/auth/login", json=payload).status_code for _ in range(11)]
            assert statuses[:10] == [401] * 10  # wrong password, but not yet rate-limited
            assert statuses[10] == 429  # 11th attempt within the window is blocked
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Config hardening
# ---------------------------------------------------------------------------


def test_production_refuses_to_start_with_a_placeholder_jwt_secret():
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="change-me-before-production-use-please")

    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="too-short")

    # A real-looking secret in production must not raise.
    Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48)


def test_production_refuses_to_start_with_debug_mode_on():
    """Final System Validation (Phase 31) — DEBUG defaults to False and
    must never be true in a production deployment; a development
    environment is free to turn it on."""
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="DEBUG"):
        Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48, DEBUG=True)

    # Off by default.
    assert Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48).DEBUG is False

    # A development environment may still turn it on.
    Settings(ENVIRONMENT="development", DEBUG=True)


def test_production_refuses_to_start_with_a_razorpay_test_mode_key():
    """Production Payment Readiness (Phase 40) — Razorpay's own
    documented convention prefixes every Key ID with rzp_test_ or
    rzp_live_; a production deployment booting with a test-mode key
    would silently accept "payments" that can never actually settle
    real money."""
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="TEST-mode"):
        Settings(
            ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48,
            RAZORPAY_KEY_ID="rzp_test_abc123", RAZORPAY_WEBHOOK_SECRET="whsec_real",
        )

    # A live-mode key must not raise.
    Settings(
        ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48,
        RAZORPAY_KEY_ID="rzp_live_abc123", RAZORPAY_WEBHOOK_SECRET="whsec_real",
    )

    # A development environment may still use a test-mode key.
    Settings(ENVIRONMENT="development", RAZORPAY_KEY_ID="rzp_test_abc123")


def test_production_refuses_to_start_with_razorpay_enabled_and_no_webhook_secret():
    """Production Payment Readiness (Phase 40) — with RAZORPAY_KEY_ID set,
    online payments are already being accepted, but a captured payment
    can only ever be confirmed asynchronously via a signed webhook.
    Booting with no RAZORPAY_WEBHOOK_SECRET configured would mean every
    such webhook is rejected at the signature check, silently stranding
    real captured payments in PENDING/PROCESSING forever."""
    from app.core.config import Settings

    with pytest.raises(RuntimeError, match="RAZORPAY_WEBHOOK_SECRET"):
        Settings(
            ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48,
            RAZORPAY_KEY_ID="rzp_live_abc123", RAZORPAY_WEBHOOK_SECRET="",
        )

    # COD-only in production (Razorpay entirely unconfigured) is a
    # legitimate deployment choice, never an error.
    Settings(ENVIRONMENT="production", JWT_SECRET_KEY="a" * 48, RAZORPAY_KEY_ID="", RAZORPAY_WEBHOOK_SECRET="")


# ---------------------------------------------------------------------------
# Integration Phase 15 — failure scenarios: an unhandled exception must
# never leak internals (stack trace, exception message, file paths) to the
# client, regardless of which endpoint or layer it originates from.
# ---------------------------------------------------------------------------


def test_an_unhandled_exception_returns_a_generic_500_never_leaking_internals(monkeypatch):
    """FastAPI's `debug` flag is never set to True anywhere in this app
    (confirmed: no DEBUG setting exists in config.py, no debug=True on the
    FastAPI() constructor) — the default, safe behavior applies. This pins
    that down with a real unhandled exception, not just a code inspection:
    a client must see a generic message, never the exception's own text or
    a stack trace."""
    from app.services import restaurants as restaurant_service

    def _boom(*args, **kwargs):
        raise RuntimeError("super secret internal detail: DB password is hunter2")

    monkeypatch.setattr(restaurant_service, "list_active_restaurants", _boom)

    engine = _http_setup()
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/v1/customer/restaurants")
            assert response.status_code == 500
            assert "hunter2" not in response.text
            assert "RuntimeError" not in response.text
            assert "Traceback" not in response.text
            assert "restaurants.py" not in response.text
    finally:
        _teardown(engine)


# ---------------------------------------------------------------------------
# Production Payment Readiness (Phase 40)
# ---------------------------------------------------------------------------


def test_docs_are_disabled_only_in_a_production_environment():
    from app.main import _should_enable_docs

    assert _should_enable_docs("production") is False
    assert _should_enable_docs("development") is True
    assert _should_enable_docs("staging") is True


def test_interactive_docs_are_reachable_in_this_non_production_test_environment():
    """The real, actually-constructed `app` object (ENVIRONMENT defaults
    to "development" throughout this whole suite — see conftest.py) must
    still serve /docs and its own OpenAPI schema — this phase's fix must
    never accidentally disable docs outside of production."""
    with TestClient(app) as client:
        assert client.get("/docs").status_code == 200
        assert client.get("/api/v1/openapi.json").status_code == 200


def test_health_endpoint_reports_ok_when_the_database_is_reachable():
    """/health opens its own SessionLocal() directly (not the request-
    scoped, dependency-overridden get_db()), so it genuinely exercises
    the real DATABASE_URL this test process is configured with
    (conftest.py's in-memory sqlite:// — empty, but SELECT 1 needs no
    table to exist)."""
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_health_endpoint_reports_503_when_the_database_is_unreachable(monkeypatch):
    from app import main as main_module

    class _BrokenSession:
        def __enter__(self):
            raise RuntimeError("connection refused")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(main_module, "SessionLocal", _BrokenSession)

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 503
        assert response.json()["status"] == "unhealthy"
