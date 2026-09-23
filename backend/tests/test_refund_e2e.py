"""Payment System Phase 36 — REFUND E2E TEST.

Runs the exact flow this phase diagrams, through the real HTTP API
against a real database, with only the Razorpay gateway itself faked:

    Successful payment -> Admin refund -> Provider refund ->
    Webhook/status update -> Internal refund record ->
    Customer payment status -> Admin visibility

using the phase's own named example throughout: a ₹500 payment, a ₹150
refund, verifying ₹350 remains refundable.

Deliberately exercises the *asynchronous* refund path (Razorpay's own
initiate-refund response comes back "pending", not "processed") so the
"Provider refund" and "Webhook/status update" steps are two genuinely
distinct events, not one collapsed step — the refund starts PROCESSING,
and only the later refund.processed webhook resolves it (and the
parent Payment's own status) to its final, settled state. This is the
one part of the diagram Phase 25's own test never exercised (that test
used provider=None, the COD/instant-complete path).
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
    PaymentProvider,
    PaymentStatus,
    Refund,
    RefundStatus,
    Restaurant,
    User,
    UserRole,
)
from app.services.payment.provider import PaymentProvider as PaymentProviderABC
from app.services.payment.provider import ProviderOrder, ProviderPayment, ProviderRefund


class FakeRazorpay(PaymentProviderABC):
    """Only the Razorpay gateway is faked; PaymentService,
    refund_service, the admin refund endpoint, and process_webhook_event
    are all completely real code. initiate_refund() deliberately returns
    "pending" (never "processed") — the honest, most common real
    Razorpay response — so create_refund() records PROCESSING and the
    refund.processed webhook is the only thing that ever resolves it."""

    name = "fake-razorpay-p36"

    def create_order(self, *, amount, currency, receipt, notes=None):
        raise NotImplementedError

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        raise NotImplementedError

    def fetch_payment(self, provider_payment_id):
        raise NotImplementedError

    def fetch_order(self, provider_order_id):
        raise NotImplementedError

    def initiate_refund(self, *, provider_payment_id, amount, notes=None):
        return ProviderRefund(provider_refund_id="rfnd_fake_p36_1", status="pending", amount=amount)

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


def test_complete_refund_flow_every_record_consistent(engine, monkeypatch):
    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", lambda *a, **k: FakeRazorpay())
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_fake_p36")

    # =====================================================================
    # STAGE 1 — Successful payment (seeded directly: a real, already-
    # captured ₹500 online payment — this phase is about refunds, not
    # re-proving capture, which Phase 34 already covers end to end).
    # =====================================================================
    with Session(engine) as seed:
        owner = User(name="Owner P36", email="p36-owner@example.com", phone="9900000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        customer = User(name="Customer P36", email="p36-customer@example.com", phone="9900000002", password_hash=hash_password("x"), role=UserRole.CUSTOMER)
        admin = User(name="Admin P36", email="p36-admin@example.com", phone="9900000003", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, customer, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P36", phone="9876500001", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("0.00"),
        )
        seed.add(restaurant)
        seed.commit()

        order = Order(
            user_id=customer.id, customer_name=customer.name, customer_email=customer.email,
            restaurant_id=str(restaurant.id), restaurant_name=restaurant.name,
            order_number="ORD-P36-0001", status=OrderStatus.DELIVERED,
            subtotal=Decimal("500.00"), delivery_fee=Decimal("0.00"), total=Decimal("500.00"),
            payment_method="razorpay", address_line="1 Road", city="Town", postal_code="123456",
        )
        seed.add(order)
        seed.commit()

        payment = Payment(
            order_id=order.id, user_id=customer.id, provider=PaymentProvider.RAZORPAY,
            payment_status=PaymentStatus.PAID, amount=Decimal("500.00"),
            razorpay_order_id="order_p36_captured", razorpay_payment_id="pay_p36_captured",
            is_verified=True,
        )
        seed.add(payment)
        seed.commit()

        order_id = order.id
        payment_id = payment.id
        customer_token = create_access_token(customer.id)
        admin_token = create_access_token(admin.id)

    customer_headers = {"Authorization": f"Bearer {customer_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    with TestClient(app) as client:
        # Sanity: the customer sees their own payment as PAID before any
        # refund exists.
        before = client.get("/api/v1/customer/payments", headers=customer_headers).json()
        assert before[0]["status"] == "paid"
        assert before[0]["amount"] == "500.00"

        # =================================================================
        # STAGE 2 — Admin refund (₹150 of the ₹500 captured)
        # =================================================================
        refund_response = client.post(
            f"/api/v1/admin/payments/{payment_id}/refund", headers=admin_headers,
            json={"amount": "150.00", "reason": "Item missing"},
        )
        assert refund_response.status_code == 200
        refund_json = refund_response.json()

        # =================================================================
        # STAGE 3 — Provider refund: Razorpay accepted the request but
        # hasn't settled it yet ("pending") — never assumed COMPLETED
        # just because the API call was accepted (Phase 24's own rule).
        # =================================================================
        assert refund_json["status"] == "PAID"  # the PAYMENT's own status — still PAID, not yet PARTIALLY_REFUNDED
        assert len(refund_json["refunds"]) == 1
        internal_refund = refund_json["refunds"][0]
        assert internal_refund["status"] == "processing"
        assert internal_refund["amount"] == "150.00"
        # Not yet settled, so not yet counted as genuinely refunded.
        assert refund_json["refunded_amount"] == "0.00"
        assert refund_json["refundable_amount"] == "350.00"  # already correctly excludes the in-flight 150

        with Session(engine) as db:
            db_refund = db.query(Refund).filter(Refund.payment_id == payment_id).one()
            assert db_refund.status == RefundStatus.PROCESSING
            assert db_refund.provider_refund_id == "rfnd_fake_p36_1"
            assert db_refund.amount == Decimal("150.00")
            assert db_refund.reason == "Item missing"

            db_payment = db.get(Payment, payment_id)
            assert db_payment.amount == Decimal("500.00")  # never overwritten by the refund
            assert db_payment.payment_status == PaymentStatus.PAID  # still PAID — nothing settled yet

        # A second refund attempt for more than what remains (350) must
        # still be rejected — the in-flight 150 correctly counts as
        # "spoken for" even before it settles.
        over_refund = client.post(
            f"/api/v1/admin/payments/{payment_id}/refund", headers=admin_headers,
            json={"amount": "350.01", "reason": "test"},
        )
        assert over_refund.status_code == 409

        # =================================================================
        # STAGE 4 — Webhook / status update: Razorpay's own refund.processed
        # event, the authoritative final-status source, arrives later.
        # =================================================================
        webhook_body = json.dumps({
            "event": "refund.processed",
            "payload": {"refund": {"entity": {
                "id": "rfnd_fake_p36_1", "payment_id": "pay_p36_captured", "amount": 15000, "status": "processed",
            }}},
        }).encode()
        webhook_signature = hmac.new(b"whsec_fake_p36", webhook_body, hashlib.sha256).hexdigest()
        webhook_response = client.post(
            "/api/v1/payments/webhooks/razorpay",
            headers={"x-razorpay-signature": webhook_signature, "x-razorpay-event-id": "evt_p36_refund"},
            content=webhook_body,
        )
        assert webhook_response.status_code == 200

        # =================================================================
        # STAGE 5 — Internal refund record: now genuinely settled.
        # =================================================================
        with Session(engine) as db:
            db_refund = db.query(Refund).filter(Refund.payment_id == payment_id).one()
            assert db_refund.status == RefundStatus.COMPLETED  # resolved by the webhook, not by the admin call

            db_payment = db.get(Payment, payment_id)
            assert db_payment.payment_status == PaymentStatus.PARTIALLY_REFUNDED  # now correctly recomputed
            assert db_payment.amount == Decimal("500.00")  # still never overwritten

        # =================================================================
        # STAGE 6 — Customer payment status
        # =================================================================
        after = client.get("/api/v1/customer/payments", headers=customer_headers).json()
        assert after[0]["status"] == "partially_refunded"
        assert after[0]["amount"] == "500.00"  # the customer's own view of the original amount is unchanged too

        # =================================================================
        # STAGE 7 — Admin visibility
        # =================================================================
        admin_detail = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers).json()
        assert admin_detail["status"] == "PARTIALLY_REFUNDED"
        assert admin_detail["refunded_amount"] == "150.00"
        assert admin_detail["refundable_amount"] == "350.00"  # the phase's own named example, verified
        assert admin_detail["latest_refund_status"] == "completed"
        assert len(admin_detail["refunds"]) == 1
        assert admin_detail["refunds"][0]["status"] == "completed"
        assert admin_detail["refunds"][0]["amount"] == "150.00"

        admin_list = client.get("/api/v1/admin/payments", headers=admin_headers).json()
        listed = next(item for item in admin_list["items"] if item["id"] == str(payment_id))
        assert listed["status"] == "PARTIALLY_REFUNDED"
        assert listed["latest_refund_status"] == "completed"

        # A duplicate delivery of the same webhook event must never
        # double-apply the refund resolution.
        duplicate_webhook = client.post(
            "/api/v1/payments/webhooks/razorpay",
            headers={"x-razorpay-signature": webhook_signature, "x-razorpay-event-id": "evt_p36_refund"},
            content=webhook_body,
        )
        assert duplicate_webhook.status_code == 200
        final_detail = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers).json()
        assert final_detail["refunded_amount"] == "150.00"  # unchanged by the redelivery
        assert len(final_detail["refunds"]) == 1  # still exactly one refund record, never doubled
