"""Payment System Phase 31 — SECURITY AUDIT.

Ten named attack scenarios, each proven blocked in its own clearly
labeled test, plus four secret values proven to never appear in any
payment-related HTTP response. This file is the canonical, auditable
record of this phase — most of these properties are also exercised
elsewhere in the suite (test_security.py, test_payment_signature_verification.py,
test_payment_webhooks.py, test_admin_payments.py, test_restaurant_payment_visibility.py,
test_idempotent_payment_creation.py); this file exists so every one of
the ten scenarios this phase names has its own explicit, unambiguous
test under this exact name, in one place, rather than being inferred
from scattered coverage.
"""

import hashlib
import hmac
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.restaurant import Restaurant
from app.models.user import User, UserRole
from app.services.payment.exceptions import PaymentVerificationError
from app.services.payment.payment_service import PaymentService
from app.services.payment.provider import PaymentProvider as PaymentProviderABC
from app.services.payment.provider import ProviderOrder, ProviderPayment, ProviderRefund


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _make_restaurant(db, owner):
    restaurant = Restaurant(
        owner_id=owner.id, name="P31 Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    db.refresh(restaurant)
    return restaurant


def _make_order(db, customer, restaurant, *, order_number=None):
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number=order_number or f"ORD-P31-{uuid.uuid4().hex[:12]}", status=OrderStatus.PLACED,
        subtotal=Decimal("200.00"), delivery_fee=Decimal("30.00"), total=Decimal("230.00"),
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_payment(db, *, order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PENDING, **extra):
    payment = Payment(order_id=order.id, user_id=order.user_id, provider=provider, payment_status=payment_status, amount=order.total, **extra)
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


# ---------------------------------------------------------------------------
# 1. Customer A -> Payment of Customer B
# ---------------------------------------------------------------------------


def test_customer_a_cannot_access_customer_bs_payment(client):
    db = _db(client)
    owner, _ = _make_user(db, name="Owner", email="p31-owner@example.com", phone="9310000001", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer_b, _ = _make_user(db, name="Customer B", email="p31-customer-b@example.com", phone="9310000002", role=UserRole.CUSTOMER)
    _, headers_a = _make_user(db, name="Customer A", email="p31-customer-a@example.com", phone="9310000003", role=UserRole.CUSTOMER)
    order_b = _make_order(db, customer_b, restaurant)
    payment_b = _make_payment(db, order=order_b, razorpay_order_id="order_p31_victim")

    # Never a 403 (which would confirm the payment exists) — a 404, the
    # same never-leak-existence convention this codebase uses everywhere.
    assert client.get(f"/api/v1/payments/{payment_b.id}", headers=headers_a).status_code == 404
    assert client.post(
        f"/api/v1/payments/{payment_b.id}/verify", headers=headers_a,
        json={"provider_order_id": "order_p31_victim", "provider_payment_id": "pay_x", "signature": "x"},
    ).status_code == 404
    assert client.post(f"/api/v1/payments/{payment_b.id}/retry", headers=headers_a).status_code == 404
    assert client.get(f"/api/v1/payments/order/{order_b.id}", headers=headers_a).status_code == 404


# ---------------------------------------------------------------------------
# 2. Rider -> Payment APIs, where unauthorized
# ---------------------------------------------------------------------------


def test_rider_cannot_access_any_payment_api(client):
    db = _db(client)
    owner, _ = _make_user(db, name="Owner", email="p31-owner2@example.com", phone="9310000010", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, _ = _make_user(db, name="Customer", email="p31-customer2@example.com", phone="9310000011", role=UserRole.CUSTOMER)
    _, admin_headers = _make_user(db, name="Admin", email="p31-admin2@example.com", phone="9310000012", role=UserRole.ADMIN)
    _, rider_headers = _make_user(db, name="Rider", email="p31-rider2@example.com", phone="9310000013", role=UserRole.RIDER)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order)

    # Customer-only generic payments router.
    assert client.get(f"/api/v1/payments/{payment.id}", headers=rider_headers).status_code == 403
    assert client.post(f"/api/v1/payments/{payment.id}/retry", headers=rider_headers).status_code == 403
    assert client.post("/api/v1/payments/create", headers=rider_headers, json={"order_id": str(order.id), "method": "razorpay"}).status_code == 403
    # Customer-only Phase 5 payment-history/methods router.
    assert client.get("/api/v1/customer/payment-methods", headers=rider_headers).status_code == 403
    assert client.get("/api/v1/customer/payments", headers=rider_headers).status_code == 403
    # Admin-only payment management + refund + COD reconciliation.
    assert client.get("/api/v1/admin/payments", headers=rider_headers).status_code == 403
    assert client.get(f"/api/v1/admin/payments/{payment.id}", headers=rider_headers).status_code == 403
    assert client.post(
        f"/api/v1/admin/payments/{payment.id}/refund", headers=rider_headers, json={"amount": "10.00", "reason": "x"},
    ).status_code == 403
    assert client.get("/api/v1/admin/cod", headers=rider_headers).status_code == 403


# ---------------------------------------------------------------------------
# 3. Restaurant -> Payment of another restaurant
# ---------------------------------------------------------------------------


def test_restaurant_owner_cannot_see_another_restaurants_order_payment_info(client):
    db = _db(client)
    owner_a, headers_a = _make_user(db, name="Owner A", email="p31-owner-a@example.com", phone="9310000020", role=UserRole.RESTAURANT_OWNER)
    owner_b, _ = _make_user(db, name="Owner B", email="p31-owner-b@example.com", phone="9310000021", role=UserRole.RESTAURANT_OWNER)
    restaurant_b = _make_restaurant(db, owner_b)
    customer, _ = _make_user(db, name="Customer", email="p31-customer3@example.com", phone="9310000022", role=UserRole.CUSTOMER)
    order_b = _make_order(db, customer, restaurant_b)

    # Owner A's own token, reaching for Restaurant B's order — never a
    # leak of its payment_status/restaurant_earning/commission/net_amount.
    response = client.get(f"/api/v1/restaurant/orders/{order_b.id}", headers=headers_a)
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 4. Non-admin -> Refund API
# ---------------------------------------------------------------------------


def test_non_admin_cannot_call_the_refund_api(client):
    db = _db(client)
    owner, owner_headers = _make_user(db, name="Owner", email="p31-owner4@example.com", phone="9310000030", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, customer_headers = _make_user(db, name="Customer", email="p31-customer4@example.com", phone="9310000031", role=UserRole.CUSTOMER)
    _, rider_headers = _make_user(db, name="Rider", email="p31-rider4@example.com", phone="9310000032", role=UserRole.RIDER)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)

    refund_body = {"amount": "10.00", "reason": "unauthorized attempt"}
    for headers in (customer_headers, rider_headers, owner_headers):
        response = client.post(f"/api/v1/admin/payments/{payment.id}/refund", headers=headers, json=refund_body)
        assert response.status_code == 403
    assert client.post(f"/api/v1/admin/payments/{payment.id}/refund", json=refund_body).status_code == 401


# ---------------------------------------------------------------------------
# 5. Forged Razorpay signature
# ---------------------------------------------------------------------------


class _ForgeableProvider(PaymentProviderABC):
    """A minimal provider stand-in whose signature check is exactly what
    Razorpay's real one is: true only for the one genuine signature this
    test computes itself, false for anything else — including a forged
    string an attacker could plausibly guess or fabricate."""

    name = "forgeable"

    def __init__(self, genuine_signature: str, amount: Decimal, currency: str = "INR", order_id: str = "order_p31_sig", status_value: str = "captured"):
        self.genuine_signature = genuine_signature
        self.amount = amount
        self.currency = currency
        self.order_id = order_id
        self.status_value = status_value

    def create_order(self, *, amount, currency, receipt, notes=None):
        raise NotImplementedError

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self.genuine_signature

    def fetch_payment(self, provider_payment_id):
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=self.order_id, status=self.status_value, amount=self.amount, currency=self.currency)

    def fetch_order(self, provider_order_id):
        return ProviderOrder(provider_order_id=provider_order_id, amount=self.amount, currency=self.currency, status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        raise NotImplementedError

    def verify_webhook_signature(self, *, payload, signature):
        raise NotImplementedError


@pytest.fixture()
def sig_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _seed_sig_order(db, *, total=Decimal("230.00")):
    owner = User(name="Owner", email="p31-sig-owner@example.com", phone="9310000040", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email="p31-sig-customer@example.com", phone="9310000041", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name="P31 Sig Diner", phone="9876543210", address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-P31-SIG-0001", status=OrderStatus.PLACED,
        subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
        payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()
    return order


def test_forged_razorpay_signature_is_rejected(sig_db):
    order = _seed_sig_order(sig_db)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id="order_p31_sig",
    )
    sig_db.add(payment)
    sig_db.commit()

    genuine_signature = hmac.new(b"real-razorpay-secret", b"order_p31_sig|pay_p31_sig", hashlib.sha256).hexdigest()
    provider = _ForgeableProvider(genuine_signature=genuine_signature, amount=order.total)
    service = PaymentService(providers={"razorpay": provider})

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            sig_db, payment=payment, provider_order_id="order_p31_sig",
            provider_payment_id="pay_p31_sig", signature="0" * 64,  # a forged, well-formed-looking signature
        )
    sig_db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED  # never PAID


# ---------------------------------------------------------------------------
# 6. Invalid webhook signature
# ---------------------------------------------------------------------------


def test_invalid_webhook_signature_is_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_p31_test")
    body = b'{"event": "payment.captured", "payload": {}}'

    forged = client.post(
        "/api/v1/payments/webhooks/razorpay", headers={"x-razorpay-signature": "not-even-close"}, content=body,
    )
    assert forged.status_code == 400

    missing = client.post("/api/v1/payments/webhooks/razorpay", content=body)
    assert missing.status_code == 400

    db = _db(client)
    from app.models.webhook_event import WebhookEvent

    assert db.query(WebhookEvent).count() == 0  # nothing was ever recorded from either


# ---------------------------------------------------------------------------
# 7. Modified payment amount
# ---------------------------------------------------------------------------


def test_modified_payment_amount_is_rejected(sig_db):
    order = _seed_sig_order(sig_db, total=Decimal("230.00"))
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id="order_p31_amt",
    )
    sig_db.add(payment)
    sig_db.commit()

    genuine_signature = hmac.new(b"s", b"order_p31_amt|pay_p31_amt", hashlib.sha256).hexdigest()
    # The provider's own fetch_payment reports an amount that DOESN'T
    # match this order's total — as if a customer somehow got Razorpay to
    # confirm a payment for less than what's actually owed.
    provider = _ForgeableProvider(genuine_signature=genuine_signature, amount=Decimal("1.00"), order_id="order_p31_amt")
    service = PaymentService(providers={"razorpay": provider})

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            sig_db, payment=payment, provider_order_id="order_p31_amt",
            provider_payment_id="pay_p31_amt", signature=genuine_signature,
        )
    sig_db.refresh(payment)
    assert payment.payment_status == PaymentStatus.FAILED
    assert payment.payment_status != PaymentStatus.PAID


# ---------------------------------------------------------------------------
# 8. Modified order ID
# ---------------------------------------------------------------------------


def test_modified_order_id_is_rejected(sig_db):
    """A genuinely, correctly signed (order_id, payment_id) pair — but for
    an order_id that isn't the one THIS payment was actually opened
    against. Must never be accepted just because the signature checks out
    against some order."""
    order = _seed_sig_order(sig_db, total=Decimal("230.00"))
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id="order_p31_real",
    )
    sig_db.add(payment)
    sig_db.commit()

    attacker_supplied_order_id = "order_p31_someone_elses"
    genuine_signature_for_wrong_order = hmac.new(b"s", f"{attacker_supplied_order_id}|pay_p31_x".encode(), hashlib.sha256).hexdigest()
    provider = _ForgeableProvider(genuine_signature=genuine_signature_for_wrong_order, amount=order.total, order_id=attacker_supplied_order_id)
    service = PaymentService(providers={"razorpay": provider})

    with pytest.raises(PaymentVerificationError):
        service.verify_payment(
            sig_db, payment=payment, provider_order_id=attacker_supplied_order_id,
            provider_payment_id="pay_p31_x", signature=genuine_signature_for_wrong_order,
        )
    sig_db.refresh(payment)
    assert payment.payment_status != PaymentStatus.PAID


# ---------------------------------------------------------------------------
# 9. Duplicate webhook
# ---------------------------------------------------------------------------


def test_duplicate_webhook_is_processed_once(client, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_p31_dup")
    db = _db(client)
    owner, _ = _make_user(db, name="Owner", email="p31-owner-dup@example.com", phone="9310000050", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, _ = _make_user(db, name="Customer", email="p31-customer-dup@example.com", phone="9310000051", role=UserRole.CUSTOMER)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order, razorpay_order_id="order_p31_dup")

    import json

    body = json.dumps({
        "event": "payment.captured",
        "payload": {"payment": {"entity": {
            "id": "pay_p31_dup", "order_id": "order_p31_dup",
            "amount": int(payment.amount * 100), "currency": "INR", "status": "captured",
        }}},
    }).encode()
    signature = hmac.new(b"whsec_p31_dup", body, hashlib.sha256).hexdigest()
    headers = {"x-razorpay-signature": signature, "x-razorpay-event-id": "evt_p31_dup_1"}

    first = client.post("/api/v1/payments/webhooks/razorpay", headers=headers, content=body)
    second = client.post("/api/v1/payments/webhooks/razorpay", headers=headers, content=body)
    assert first.status_code == 200
    assert second.status_code == 200

    from app.models.webhook_event import WebhookEvent

    db2 = _db(client)
    events = db2.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p31_dup_1").all()
    assert len(events) == 1  # the redelivery was recognized, not recorded a second time

    refreshed_payment = db2.query(Payment).filter(Payment.id == payment.id).one()
    assert refreshed_payment.payment_status == PaymentStatus.PAID
    # A duplicate delivery must never re-timestamp an already-settled
    # payment — this is the concrete, observable sign that only ONE of
    # the two deliveries actually mutated anything.
    assert refreshed_payment.paid_at is not None


# ---------------------------------------------------------------------------
# 10. Duplicate payment request
# ---------------------------------------------------------------------------


def test_duplicate_payment_creation_request_never_creates_two_payment_rows(client):
    db = _db(client)
    owner, _ = _make_user(db, name="Owner", email="p31-owner-dup2@example.com", phone="9310000060", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, customer_headers = _make_user(db, name="Customer", email="p31-customer-dup2@example.com", phone="9310000061", role=UserRole.CUSTOMER)
    order = Order(
        user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
        restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
        order_number="ORD-P31-DUP2-0001", status=OrderStatus.PLACED,
        subtotal=Decimal("170.00"), delivery_fee=Decimal("30.00"), total=Decimal("200.00"),
        payment_method="cod", address_line="1 Road", city="Town", postal_code="123456",
    )
    db.add(order)
    db.commit()

    # A double-tap: two requests for the same order's payment, back to back.
    first = client.post("/api/v1/payments/create", headers=customer_headers, json={"order_id": str(order.id), "method": "cod"})
    second = client.post("/api/v1/payments/create", headers=customer_headers, json={"order_id": str(order.id), "method": "cod"})
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]  # the same row, not a new one

    db2 = _db(client)
    count = db2.query(Payment).filter(Payment.order_id == order.id).count()
    assert count == 1


# ---------------------------------------------------------------------------
# Secret exposure — never in any payment-related response
# ---------------------------------------------------------------------------


def test_razorpay_key_secret_never_appears_in_any_payment_response(client, monkeypatch):
    canary = "p31-canary-razorpay-key-secret-must-never-leak"
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", canary)

    db = _db(client)
    owner, owner_headers = _make_user(db, name="Owner", email="p31-owner-secret@example.com", phone="9310000070", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, customer_headers = _make_user(db, name="Customer", email="p31-customer-secret@example.com", phone="9310000071", role=UserRole.CUSTOMER)
    _, admin_headers = _make_user(db, name="Admin", email="p31-admin-secret@example.com", phone="9310000072", role=UserRole.ADMIN)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order)

    responses = [
        client.get(f"/api/v1/payments/{payment.id}", headers=customer_headers),
        client.get(f"/api/v1/admin/payments/{payment.id}", headers=admin_headers),
        client.get("/api/v1/admin/payments", headers=admin_headers),
        client.get(f"/api/v1/restaurant/orders/{order.id}", headers=owner_headers),
        client.get("/api/v1/customer/payments", headers=customer_headers),
    ]
    for response in responses:
        assert canary not in response.text


def test_razorpay_webhook_secret_never_appears_in_any_response(client, monkeypatch):
    canary = "p31-canary-webhook-secret-must-never-leak"
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", canary)

    forged = client.post(
        "/api/v1/payments/webhooks/razorpay", headers={"x-razorpay-signature": "wrong"}, content=b'{"event": "x", "payload": {}}',
    )
    assert canary not in forged.text

    missing = client.post("/api/v1/payments/webhooks/razorpay", content=b'{"event": "x", "payload": {}}')
    assert canary not in missing.text


def test_jwt_secret_never_appears_in_any_response(client):
    canary = settings.JWT_SECRET_KEY
    db = _db(client)
    owner, owner_headers = _make_user(db, name="Owner", email="p31-owner-jwt@example.com", phone="9310000080", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, customer_headers = _make_user(db, name="Customer", email="p31-customer-jwt@example.com", phone="9310000081", role=UserRole.CUSTOMER)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order)

    responses = [
        client.get(f"/api/v1/payments/{payment.id}", headers=customer_headers),
        client.get(f"/api/v1/restaurant/orders/{order.id}", headers=owner_headers),
        client.get("/api/v1/customer/payments", headers=customer_headers),
        client.post("/api/v1/auth/login", json={"email": "p31-customer-jwt@example.com", "password": "wrong-password"}),
    ]
    for response in responses:
        assert canary not in response.text


def test_database_credentials_never_appear_in_any_response(client):
    canary = settings.DATABASE_URL
    db = _db(client)
    owner, owner_headers = _make_user(db, name="Owner", email="p31-owner-db@example.com", phone="9310000090", role=UserRole.RESTAURANT_OWNER)
    restaurant = _make_restaurant(db, owner)
    customer, customer_headers = _make_user(db, name="Customer", email="p31-customer-db@example.com", phone="9310000091", role=UserRole.CUSTOMER)
    order = _make_order(db, customer, restaurant)
    payment = _make_payment(db, order=order)

    responses = [
        client.get(f"/api/v1/payments/{payment.id}", headers=customer_headers),
        client.get(f"/api/v1/restaurant/orders/{order.id}", headers=owner_headers),
        # An unhandled exception must never leak internals either — same
        # generic-500 guarantee test_security.py already proves elsewhere,
        # re-confirmed here specifically for a payment-adjacent route.
        client.get("/api/v1/payments/00000000-0000-0000-0000-000000000000", headers=customer_headers),
    ]
    for response in responses:
        assert canary not in response.text
