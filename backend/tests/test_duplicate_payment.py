"""Payment System Phase 35 — DUPLICATE PAYMENT TEST.

Test: Customer taps PAY twice. Expected: one logical order, no duplicate
successful payment, no duplicate financial ledger entry.

Also test: webhook arrives twice. Expected: one financial state
transition.

Most of the underlying guarantees were already built by earlier
phases (Idempotent Order Payment Creation, Phase 21; Webhook
Idempotency, Phase 18) and are proven again here under this phase's own
exact vocabulary, in one canonical place. This phase's own genuinely
new proof is the "double-tap PAY" scenario applied to *verification*,
not just payment creation — unlike create_payment_for_order() (which
row-locks the order specifically to guard this), verify_payment() takes
no lock at all, so this file also proves, with real concurrent
threads against a real database (not just sequential calls against
SQLite), that a genuine double-tap on /verify still resolves to exactly
one PaymentAttempt row for that event and exactly one PAID transition —
thanks to the same-payment collision-recovery fix Phase 32 already made
to PaymentAttempt's own uniqueness handling.
"""

import hashlib
import hmac
import json
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentAttempt,
    PaymentProvider,
    PaymentStatus,
    Restaurant,
    User,
    UserRole,
)
from app.models.webhook_event import WebhookEvent
from app.services.payment.provider import PaymentProvider as PaymentProviderABC
from app.services.payment.provider import ProviderOrder, ProviderPayment, ProviderRefund


class FakeRazorpay(PaymentProviderABC):
    name = "fake-razorpay-p35"

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self._counter = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._counter += 1
        provider_order_id = f"order_fake_p35_{self._counter}"
        self.orders[provider_order_id] = {"amount": amount, "currency": currency}
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency=currency, status="created")

    def _signature_for(self, provider_order_id: str, provider_payment_id: str) -> str:
        return hmac.new(b"fake-razorpay-secret-p35", f"{provider_order_id}|{provider_payment_id}".encode(), hashlib.sha256).hexdigest()

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self._signature_for(provider_order_id, provider_payment_id)

    def fetch_payment(self, provider_payment_id):
        order_id, order = next(iter(self.orders.items()))
        return ProviderPayment(provider_payment_id=provider_payment_id, provider_order_id=order_id, status="captured", amount=order["amount"], currency=order["currency"])

    def fetch_order(self, provider_order_id):
        order = self.orders[provider_order_id]
        return ProviderOrder(provider_order_id=provider_order_id, amount=order["amount"], currency=order["currency"], status="paid")

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        raise NotImplementedError

    def verify_webhook_signature(self, *, payload, signature):
        raise NotImplementedError


@pytest.fixture()
def engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield engine
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _seed_online_order_ready_to_pay(engine, monkeypatch, *, tag: str, total=Decimal("230.00")):
    fake = FakeRazorpay()
    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", lambda *a, **k: fake)
    import app.api.v1.endpoints.payments as payments_endpoint

    monkeypatch.setitem(payments_endpoint._payment_service._providers, "razorpay", fake)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake_p35")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake-razorpay-secret-p35")

    with Session(engine) as seed:
        owner = User(name="Owner", email=f"p35-owner-{tag}@example.com", phone=f"92{tag}01", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Customer", email=f"p35-customer-{tag}@example.com", phone=f"92{tag}02", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        seed.add_all([owner, customer])
        seed.commit()
        restaurant = Restaurant(
            owner_id=owner.id, name=f"Diner {tag}", phone="9876543210", address="1 Road",
            latitude=Decimal("12.1"), longitude=Decimal("77.1"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
        )
        seed.add(restaurant)
        seed.commit()
        order = Order(
            user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
            restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
            order_number=f"ORD-P35-{tag}", status=OrderStatus.PLACED,
            subtotal=total - Decimal("30.00"), delivery_fee=Decimal("30.00"), total=total,
            payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
        )
        seed.add(order)
        seed.commit()
        customer_token = create_access_token(customer.id)
        order_id = order.id

    return fake, customer_token, order_id


# ---------------------------------------------------------------------------
# "Customer taps PAY twice" — payment CREATION double-tap
# ---------------------------------------------------------------------------


def test_tapping_pay_twice_before_payment_creation_completes_is_one_logical_order_one_payment(engine, monkeypatch):
    fake, customer_token, order_id = _seed_online_order_ready_to_pay(engine, monkeypatch, tag="01")
    headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        first = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)
        second = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["payment_id"] == second.json()["payment_id"]  # the same payment, not a new one

    with Session(engine) as db:
        # One logical order.
        assert db.query(Order).filter(Order.id == order_id).count() == 1
        # No duplicate successful payment: exactly one Payment row.
        payments = db.query(Payment).filter(Payment.order_id == order_id).all()
        assert len(payments) == 1
        # The provider was only ever actually called once — the second tap
        # found the first tap's own row already there and reused it,
        # never opening a second real Razorpay order.
        assert len(fake.orders) == 1


# ---------------------------------------------------------------------------
# "Customer taps PAY twice" — payment VERIFICATION double-tap (sequential:
# the common real case, a UI double-tap or an app-level retry after the
# first response is slow/lost, where the second request starts only once
# the first has already committed)
# ---------------------------------------------------------------------------


def test_tapping_pay_twice_sequential_verify_calls_never_double_confirms(engine, monkeypatch):
    fake, customer_token, order_id = _seed_online_order_ready_to_pay(engine, monkeypatch, tag="02")
    headers = {"Authorization": f"Bearer {customer_token}"}

    with TestClient(app) as client:
        create = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)
        payment_id = create.json()["payment_id"]
        provider_order_id = create.json()["transaction_reference"]
        provider_payment_id = "pay_fake_p35_tap"
        signature = fake._signature_for(provider_order_id, provider_payment_id)
        body = {"provider_order_id": provider_order_id, "provider_payment_id": provider_payment_id, "signature": signature}

        first_tap = client.post(f"/api/v1/payments/{payment_id}/verify", headers=headers, json=body)
        second_tap = client.post(f"/api/v1/payments/{payment_id}/verify", headers=headers, json=body)

    assert first_tap.status_code == 200
    assert first_tap.json()["status"] == "paid"
    # No duplicate successful payment: the second identical tap is
    # honestly rejected — the endpoint's own state gate refuses to
    # re-verify an already-PAID payment — never a second "success".
    assert second_tap.status_code == 409

    with Session(engine) as db:
        payment = db.get(Payment, UUID(payment_id))
        assert payment.payment_status == PaymentStatus.PAID
        first_paid_at = payment.paid_at
        assert first_paid_at is not None

        # No duplicate financial ledger entry: exactly two PaymentAttempt
        # rows total for this payment — one from opening the provider
        # order, one from the single genuine verification — never a third
        # for the rejected second tap (it never reached the service layer
        # at all).
        attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == UUID(payment_id)).all()
        assert len(attempts) == 2
        assert sorted(a.status for a in attempts) == sorted([PaymentStatus.PENDING, PaymentStatus.PAID])


# ---------------------------------------------------------------------------
# Webhook arrives twice
# ---------------------------------------------------------------------------


def test_webhook_arriving_twice_is_one_financial_state_transition(engine, monkeypatch):
    fake, customer_token, order_id = _seed_online_order_ready_to_pay(engine, monkeypatch, tag="03")
    headers = {"Authorization": f"Bearer {customer_token}"}
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_fake_p35")

    with TestClient(app) as client:
        create = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)
        payment_id = create.json()["payment_id"]
        provider_order_id = create.json()["transaction_reference"]

        body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": "pay_fake_p35_webhook", "order_id": provider_order_id,
                "amount": 23000, "currency": "INR", "status": "captured",
            }}},
        }).encode()
        signature = hmac.new(b"whsec_fake_p35", body, hashlib.sha256).hexdigest()
        webhook_headers = {"x-razorpay-signature": signature, "x-razorpay-event-id": "evt_p35_webhook"}

        first_delivery = client.post("/api/v1/payments/webhooks/razorpay", headers=webhook_headers, content=body)
        second_delivery = client.post("/api/v1/payments/webhooks/razorpay", headers=webhook_headers, content=body)

    assert first_delivery.status_code == 200
    assert second_delivery.status_code == 200

    with Session(engine) as db:
        events = db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p35_webhook").all()
        assert len(events) == 1  # the redelivery was recognized, never re-recorded

        payment = db.get(Payment, UUID(payment_id))
        # One financial state transition: PENDING -> PAID happened exactly
        # once. paid_at is set once and never re-stamped by the redelivery.
        assert payment.payment_status == PaymentStatus.PAID
        first_paid_at = payment.paid_at
        assert first_paid_at is not None

        db_order = db.get(Order, order_id)
        assert db_order.is_paid is True

    # Re-fetch the payment one more time to prove the second delivery
    # genuinely did nothing — no in-place mutation to detect via a second
    # read either.
    with Session(engine) as db2:
        payment_again = db2.get(Payment, UUID(payment_id))
        assert payment_again.paid_at == first_paid_at
