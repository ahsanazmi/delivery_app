"""Payment System Phase 34 — COMPLETE RAZORPAY E2E TEST.

Runs the exact flow this phase diagrams, through the real HTTP API
against a real database, with only the Razorpay gateway itself faked
(everything on this backend's own side — PaymentService, the webhook
handler, signature/amount verification — is completely real):

    Customer -> Checkout -> Online Payment -> Backend Creates Razorpay
    Order -> Razorpay Checkout -> Payment -> Frontend Callback ->
    Backend Verification -> Webhook -> Payment PAID -> Order Payment
    Status Updated -> Restaurant -> Rider -> Delivery -> Admin

and verifies every one of the nine records this phase names are
consistent with each other at the end: Order, Payment, PaymentAttempt,
Provider Order (the fake gateway's own order), Provider Payment (the
fake gateway's own payment), WebhookEvent, Restaurant earning,
Commission, Rider earning.
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
    ApprovalStatus,
    CommissionRule,
    CommissionType,
    DeliveryPartner,
    Order,
    OrderStatus,
    Payment,
    PaymentAttempt,
    PaymentProvider,
    PaymentStatus,
    Product,
    Restaurant,
    RiderEarning,
    User,
    UserRole,
)
from app.models.webhook_event import WebhookEvent
from app.services.payment.provider import PaymentProvider as PaymentProviderABC
from app.services.payment.provider import ProviderOrder, ProviderPayment, ProviderRefund


class FakeRazorpay(PaymentProviderABC):
    """The only faked thing in this whole test — the real Razorpay
    gateway itself. Everything this backend does around it (opening an
    order, verifying a signature, cross-checking the provider's own
    reported amount, processing a webhook) is completely real code,
    genuinely exercised."""

    name = "fake-razorpay"

    def __init__(self):
        self.orders: dict[str, dict] = {}
        self._counter = 0

    def create_order(self, *, amount, currency, receipt, notes=None):
        self._counter += 1
        provider_order_id = f"order_fake_p34_{self._counter}"
        self.orders[provider_order_id] = {"amount": amount, "currency": currency, "receipt": receipt}
        return ProviderOrder(provider_order_id=provider_order_id, amount=amount, currency=currency, status="created")

    def _signature_for(self, provider_order_id: str, provider_payment_id: str) -> str:
        return hmac.new(b"fake-razorpay-secret", f"{provider_order_id}|{provider_payment_id}".encode(), hashlib.sha256).hexdigest()

    def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
        return signature == self._signature_for(provider_order_id, provider_payment_id)

    def fetch_payment(self, provider_payment_id):
        order_id, order = next(iter(self.orders.items()))
        return ProviderPayment(
            provider_payment_id=provider_payment_id, provider_order_id=order_id,
            status="captured", amount=order["amount"], currency=order["currency"],
        )

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


def test_complete_razorpay_flow_every_record_consistent(engine, monkeypatch):
    fake = FakeRazorpay()
    # Payment creation (app/services/payments.py::record_order_payment)
    # constructs a fresh PaymentService() per call — patching the class
    # itself makes that fresh construction pick up the fake.
    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", lambda *a, **k: fake)
    # /payments/{id}/verify goes through a module-level PaymentService()
    # singleton, already constructed with the real class before this
    # test's own monkeypatch can apply — its provider dict is patched
    # directly instead, same underlying fake instance either way.
    import app.api.v1.endpoints.payments as payments_endpoint

    monkeypatch.setitem(payments_endpoint._payment_service._providers, "razorpay", fake)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "rzp_test_fake_p34")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "fake-razorpay-secret")
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "whsec_fake_p34")

    # ---- Seed: restaurant owner, admin, a 12% platform commission ----
    with Session(engine) as seed:
        owner = User(name="Owner P34", email="p34-owner@example.com", phone="9800000001", password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
        admin = User(name="Admin P34", email="p34-admin@example.com", phone="9800000002", password_hash=hash_password("x"), role=UserRole.ADMIN)
        seed.add_all([owner, admin])
        seed.commit()

        restaurant = Restaurant(
            owner_id=owner.id, name="Chai House P34", phone="9876500001", address="Main Road",
            latitude=Decimal("12.9716"), longitude=Decimal("77.5946"),
            minimum_order=Decimal("0.00"), delivery_fee=Decimal("35.00"),
        )
        seed.add(restaurant)
        seed.commit()

        product = Product(restaurant_id=restaurant.id, name="Dosa", price=Decimal("150.00"))
        seed.add(product)
        seed.commit()
        product_id = str(product.id)

        seed.add(CommissionRule(restaurant_id=None, commission_type=CommissionType.PERCENTAGE, value=Decimal("12")))
        seed.commit()

        owner_token = create_access_token(owner.id)
        admin_token = create_access_token(admin.id)

    with TestClient(app) as client:
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        register_customer = client.post(
            "/api/v1/auth/register",
            json={"name": "Customer P34", "email": "p34-customer@example.com", "password": "secure-pass-123", "phone": "9800000010", "role": "CUSTOMER"},
        )
        assert register_customer.status_code == 201
        customer_token = client.post("/api/v1/auth/login", json={"email": "p34-customer@example.com", "password": "secure-pass-123"}).json()["access_token"]
        customer_headers = {"Authorization": f"Bearer {customer_token}"}

        register_rider = client.post(
            "/api/v1/auth/register",
            json={"name": "Rider P34", "email": "p34-rider@example.com", "password": "secure-pass-123", "phone": "9800000011", "role": "RIDER"},
        )
        assert register_rider.status_code == 201
        rider_id = register_rider.json()["id"]
        rider_token = client.post("/api/v1/auth/login", json={"email": "p34-rider@example.com", "password": "secure-pass-123"}).json()["access_token"]
        rider_headers = {"Authorization": f"Bearer {rider_token}"}

        with Session(engine) as db:
            db.add(DeliveryPartner(user_id=UUID(rider_id), approval_status=ApprovalStatus.APPROVED, is_online=True))
            db.commit()

        # =====================================================================
        # STAGE 1 — Customer -> Checkout -> Online Payment (Order placed)
        # =====================================================================
        address = client.post(
            "/api/v1/customer/addresses", headers=customer_headers,
            json={
                "label": "Home", "recipient_name": "Customer P34", "phone": "9800000010",
                "address_line": "1 MG Road", "city": "Bengaluru", "state": "Karnataka", "postal_code": "560001",
                "latitude": "12.9750", "longitude": "77.6050",
            },
        )
        assert address.status_code == 201
        address_id = address.json()["id"]

        client.post("/api/v1/customer/cart/items", headers=customer_headers, json={"product_id": product_id, "quantity": 1})
        place = client.post("/api/v1/customer/orders", headers=customer_headers, json={"address_id": address_id, "payment_method": "razorpay"})
        assert place.status_code == 201
        order_id = place.json()["id"]
        assert place.json()["payment_method"] == "razorpay"
        assert place.json()["total"] == "185.00"  # 150.00 + 35.00 delivery

        # =====================================================================
        # STAGE 2 — Backend Creates Razorpay Order
        # =====================================================================
        create_payment = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=customer_headers)
        assert create_payment.status_code == 200
        payment_json = create_payment.json()
        payment_id = payment_json["payment_id"]
        provider_order_id = payment_json["transaction_reference"]
        assert provider_order_id in fake.orders
        assert fake.orders[provider_order_id]["amount"] == Decimal("185.00")

        with Session(engine) as db:
            payment = db.get(Payment, UUID(payment_id))
            assert payment.provider == PaymentProvider.RAZORPAY
            assert payment.payment_status == PaymentStatus.PENDING
            assert payment.razorpay_order_id == provider_order_id
            assert payment.amount == Decimal("185.00")

            attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == UUID(payment_id)).all()
            assert len(attempts) == 1  # the order-creation attempt
            assert attempts[0].status == PaymentStatus.PENDING
            assert attempts[0].provider_order_id == provider_order_id

            db_order = db.get(Order, UUID(order_id))
            assert db_order.is_paid is False  # not yet — only the provider order was opened

        # =====================================================================
        # STAGE 3/4 — Razorpay Checkout -> Payment (simulated at the gateway)
        # =====================================================================
        provider_payment_id = "pay_fake_p34_1"
        genuine_signature = fake._signature_for(provider_order_id, provider_payment_id)

        # =====================================================================
        # STAGE 5/6 — Frontend Callback -> Backend Verification
        # =====================================================================
        verify = client.post(
            f"/api/v1/payments/{payment_id}/verify", headers=customer_headers,
            json={"provider_order_id": provider_order_id, "provider_payment_id": provider_payment_id, "signature": genuine_signature},
        )
        assert verify.status_code == 200
        assert verify.json()["status"] == "paid"

        with Session(engine) as db:
            payment = db.get(Payment, UUID(payment_id))
            assert payment.payment_status == PaymentStatus.PAID
            assert payment.is_verified is True
            assert payment.razorpay_payment_id == provider_payment_id
            assert payment.amount == Decimal("185.00")  # never overwritten by verification

            db_order = db.get(Order, UUID(order_id))
            assert db_order.is_paid is True
            assert db_order.payment_status == "paid"

            attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == UUID(payment_id)).order_by(PaymentAttempt.created_at).all()
            assert len(attempts) == 2  # order-creation attempt + this verify attempt
            assert attempts[1].status == PaymentStatus.PAID
            assert attempts[1].provider_payment_id == provider_payment_id

        # =====================================================================
        # STAGE 7 — Webhook (arriving after verification — must be idempotent)
        # =====================================================================
        webhook_body = json.dumps({
            "event": "payment.captured",
            "payload": {"payment": {"entity": {
                "id": provider_payment_id, "order_id": provider_order_id,
                "amount": 18500, "currency": "INR", "status": "captured",
            }}},
        }).encode()
        webhook_signature = hmac.new(b"whsec_fake_p34", webhook_body, hashlib.sha256).hexdigest()
        webhook_response = client.post(
            "/api/v1/payments/webhooks/razorpay",
            headers={"x-razorpay-signature": webhook_signature, "x-razorpay-event-id": "evt_p34_1"},
            content=webhook_body,
        )
        assert webhook_response.status_code == 200

        with Session(engine) as db:
            events = db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p34_1").all()
            assert len(events) == 1
            assert events[0].outcome == "duplicate_ignored"  # verification already settled it first
            assert events[0].payment_id == UUID(payment_id)

            # STAGE 8/9 — Payment PAID / Order Payment Status Updated: still
            # correct, untouched by the redundant webhook.
            payment = db.get(Payment, UUID(payment_id))
            assert payment.payment_status == PaymentStatus.PAID
            db_order = db.get(Order, UUID(order_id))
            assert db_order.is_paid is True

        # =====================================================================
        # STAGE 10/11/12 — Restaurant -> Rider -> Delivery
        # =====================================================================
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/accept", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/preparing", headers=owner_headers).status_code == 200
        assert client.post(f"/api/v1/restaurant/orders/{order_id}/ready", headers=owner_headers).status_code == 200

        assert client.post(f"/api/v1/rider/deliveries/{order_id}/accept", headers=rider_headers).status_code == 200
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/pickup", headers=rider_headers).status_code == 200
        assert client.post(f"/api/v1/rider/deliveries/{order_id}/start", headers=rider_headers).status_code == 200
        # No COD collection step for an online payment — already paid.
        complete = client.post(f"/api/v1/rider/deliveries/{order_id}/complete", headers=rider_headers)
        assert complete.status_code == 200
        assert complete.json()["status"] == "delivered"

        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            assert db_order.status == OrderStatus.DELIVERED

            earnings = db.query(RiderEarning).filter(RiderEarning.rider_id == UUID(rider_id)).all()
            assert len(earnings) == 1
            assert earnings[0].amount == Decimal("35.00")  # the restaurant's own delivery_fee
            assert earnings[0].order_id == UUID(order_id)

        # =====================================================================
        # STAGE 13 — Admin: every named record consistent
        # =====================================================================
        admin_payment = client.get(f"/api/v1/admin/payments/{payment_id}", headers=admin_headers)
        assert admin_payment.status_code == 200
        admin_payment_json = admin_payment.json()
        assert admin_payment_json["status"] == "PAID"
        assert admin_payment_json["provider"] == "Razorpay"
        assert Decimal(admin_payment_json["amount"]) == Decimal("185.00")

        overview = client.get("/api/v1/admin/reports/overview", headers=admin_headers).json()
        assert Decimal(overview["revenue"]) == Decimal("185.00")
        assert Decimal(overview["platform_commission"]) == Decimal("18.00")  # 12% of 150.00 subtotal
        assert Decimal(overview["restaurant_earnings"]) == Decimal("132.00")  # 150.00 - 18.00
        assert Decimal(overview["rider_earnings"]) == Decimal("35.00")
        # The reconciliation identity: every rupee of the customer's online
        # payment is accounted for exactly once, split three ways.
        assert (
            Decimal(overview["restaurant_earnings"]) + Decimal(overview["platform_commission"]) + Decimal(overview["rider_earnings"])
        ) == Decimal("185.00") == Decimal(overview["revenue"])

        # Final cross-check of all nine named records, directly:
        with Session(engine) as db:
            db_order = db.get(Order, UUID(order_id))
            db_payment = db.get(Payment, UUID(payment_id))
            db_attempts = db.query(PaymentAttempt).filter(PaymentAttempt.payment_id == UUID(payment_id)).all()
            db_webhook_event = db.query(WebhookEvent).filter(WebhookEvent.event_id == "evt_p34_1").one()
            db_earning = db.query(RiderEarning).filter(RiderEarning.order_id == UUID(order_id)).one()

            # Order <-> Payment
            assert db_payment.order_id == db_order.id
            assert db_payment.amount == db_order.total
            # Payment <-> Provider Order / Provider Payment (the fake gateway's own records)
            assert db_payment.razorpay_order_id in fake.orders
            assert db_payment.razorpay_payment_id == provider_payment_id
            # Payment <-> PaymentAttempt (both attempts reference this exact payment)
            assert all(a.payment_id == db_payment.id for a in db_attempts)
            # Payment <-> WebhookEvent
            assert db_webhook_event.payment_id == db_payment.id
            assert db_webhook_event.provider_payment_id == db_payment.razorpay_payment_id
            # Order <-> Commission (frozen snapshot, still exactly what it was at creation)
            assert db_order.commission_amount == Decimal("18.00")
            # Order <-> Rider earning
            assert db_earning.order_id == db_order.id
            assert db_earning.amount == Decimal("35.00")
