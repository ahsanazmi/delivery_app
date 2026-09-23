"""Payment System Phase 5 — Payment API Design.

Covers /api/v1/payments/* end to end through real HTTP calls (TestClient),
not direct service calls — this is the layer the phase itself is about:
authentication, order/payment ownership, payment state, server-derived
amounts, and safe responses, for every one of the five endpoints. The
underlying orchestration (PaymentService) already has its own dedicated
tests from Phase 4; these tests exist to prove the HTTP boundary itself
enforces every one of this phase's five named requirements.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order


@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_customer_with_order(client, tag="a"):
    db = _db(client)
    owner = User(name="Owner", email=f"owner-api-{tag}@example.com", phone=f"940000000{tag}"[:10], password_hash=hash_password("x"), role=UserRole.RESTAURANT_OWNER)
    customer = User(name="Customer", email=f"customer-api-{tag}@example.com", phone=f"941000000{tag}"[:10], password_hash=hash_password("x"), role=UserRole.CUSTOMER)
    db.add_all([owner, customer])
    db.commit()
    restaurant = Restaurant(
        owner_id=owner.id, name=f"API Diner {tag}", phone=f"942000000{tag}"[:10], address="1 Road",
        latitude=Decimal("12.1"), longitude=Decimal("77.1"),
        minimum_order=Decimal("0.00"), delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("200.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home", "recipient_name": "Customer", "phone": f"941000000{tag}"[:10],
        "address_line": "1 Road", "city": "Town", "state": "ST", "postal_code": "123456",
    })
    order = create_order(db, customer, address.id)
    token = create_access_token(customer.id)
    db.close()
    return {"headers": {"Authorization": f"Bearer {token}"}, "order_id": str(order.id), "order_total": order.total, "customer_id": customer.id}


# ---------------------------------------------------------------------------
# Authentication — every endpoint
# ---------------------------------------------------------------------------


def test_every_payment_endpoint_requires_authentication(client):
    order_id = "00000000-0000-0000-0000-000000000000"
    payment_id = "00000000-0000-0000-0000-000000000001"

    assert client.post("/api/v1/payments/create", json={"order_id": order_id, "method": "cod"}).status_code == 401
    assert client.get(f"/api/v1/payments/{payment_id}").status_code == 401
    assert client.post(f"/api/v1/payments/{payment_id}/verify", json={"provider_order_id": "x", "provider_payment_id": "y", "signature": "z"}).status_code == 401
    assert client.post(f"/api/v1/payments/{payment_id}/retry").status_code == 401
    assert client.get(f"/api/v1/payments/order/{order_id}").status_code == 401


# ---------------------------------------------------------------------------
# POST /payments/create
# ---------------------------------------------------------------------------


def test_create_payment_cod_succeeds_with_server_derived_amount(client):
    a = _make_customer_with_order(client)
    response = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"})
    assert response.status_code == 201
    body = response.json()
    assert body["method"] == "cod"
    assert Decimal(body["amount"]) == a["order_total"]
    assert "user_id" not in body  # safe response — never echoes the owner's id
    assert "razorpay_signature" not in body


def test_create_payment_rejects_someone_elses_order(client):
    a = _make_customer_with_order(client, tag="a")
    b = _make_customer_with_order(client, tag="b")
    response = client.post("/api/v1/payments/create", headers=b["headers"], json={"order_id": a["order_id"], "method": "cod"})
    assert response.status_code == 404


def test_create_payment_is_idempotent(client):
    a = _make_customer_with_order(client)
    first = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"})
    second = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"})
    assert first.json()["id"] == second.json()["id"]


def test_create_payment_for_a_nonexistent_order_is_404_not_500(client):
    """Automated Tests (Phase 38) — Payment creation. Distinct from
    test_create_payment_rejects_someone_elses_order above (a real order
    owned by a different customer): this order id has no Order row at
    all — the same ownership lookup must still resolve to a clean 404,
    never an unhandled error from a join/lookup that assumed the row
    exists."""
    a = _make_customer_with_order(client)
    random_order_id = "00000000-0000-0000-0000-000000000123"
    response = client.post(
        "/api/v1/payments/create", headers=a["headers"], json={"order_id": random_order_id, "method": "cod"}
    )
    assert response.status_code == 404


def test_create_payment_online_without_credentials_returns_503(client):
    a = _make_customer_with_order(client)
    response = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "razorpay"})
    assert response.status_code == 503  # honest refusal — never a fabricated payment


def test_create_payment_ignores_any_amount_field_in_the_request_body(client):
    a = _make_customer_with_order(client)
    response = client.post(
        "/api/v1/payments/create", headers=a["headers"],
        json={"order_id": a["order_id"], "method": "cod", "amount": "0.01"},
    )
    assert response.status_code == 201
    assert Decimal(response.json()["amount"]) == a["order_total"]


# ---------------------------------------------------------------------------
# GET /payments/{id}
# ---------------------------------------------------------------------------


def test_get_payment_by_id_returns_the_owners_own_payment(client):
    a = _make_customer_with_order(client)
    created = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"}).json()
    fetched = client.get(f"/api/v1/payments/{created['id']}", headers=a["headers"])
    assert fetched.status_code == 200
    assert fetched.json()["id"] == created["id"]


def test_customer_a_cannot_access_customer_bs_payment(client):
    """The phase's own explicit requirement, verified directly at the API
    boundary — a real HTTP request, not a service-layer assertion."""
    a = _make_customer_with_order(client, tag="a")
    b = _make_customer_with_order(client, tag="b")
    payment_b = client.post("/api/v1/payments/create", headers=b["headers"], json={"order_id": b["order_id"], "method": "cod"}).json()

    blocked = client.get(f"/api/v1/payments/{payment_b['id']}", headers=a["headers"])
    assert blocked.status_code == 404  # never leaks that it exists, never returns it


def test_get_payment_for_a_nonexistent_id_is_404_not_500(client):
    a = _make_customer_with_order(client)
    response = client.get("/api/v1/payments/00000000-0000-0000-0000-000000000099", headers=a["headers"])
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /payments/{id}/verify
# ---------------------------------------------------------------------------


def test_verify_rejects_a_cod_payment(client):
    a = _make_customer_with_order(client)
    created = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"}).json()
    response = client.post(
        f"/api/v1/payments/{created['id']}/verify", headers=a["headers"],
        json={"provider_order_id": "x", "provider_payment_id": "y", "signature": "z"},
    )
    assert response.status_code == 400


def test_verify_rejects_an_already_paid_payment(client):
    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(
        order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.PAID, is_verified=True,
    )
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(
        f"/api/v1/payments/{payment_id}/verify", headers=a["headers"],
        json={"provider_order_id": "x", "provider_payment_id": "y", "signature": "z"},
    )
    assert response.status_code == 409


def test_verify_rejects_a_request_missing_the_signature_field(client):
    """Automated Tests (Phase 38) — Signature verification. A missing
    signature (the field itself absent, not merely a wrong value —
    every other signature test in this suite forges or tampers a
    *present* signature) must never reach PaymentService.verify_payment()
    at all; FastAPI/Pydantic's own required-field validation is the
    first gate, and this proves it actually holds for this endpoint
    rather than just being assumed from the schema."""
    a = _make_customer_with_order(client)
    created = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"}).json()
    response = client.post(
        f"/api/v1/payments/{created['id']}/verify", headers=a["headers"],
        json={"provider_order_id": "x", "provider_payment_id": "y"},
    )
    assert response.status_code == 422


def test_customer_a_cannot_verify_customer_bs_payment(client):
    a = _make_customer_with_order(client, tag="a")
    b = _make_customer_with_order(client, tag="b")
    db = _db(client)
    payment = Payment(order_id=UUID(b["order_id"]), user_id=b["customer_id"], provider=PaymentProvider.RAZORPAY, amount=b["order_total"])
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(
        f"/api/v1/payments/{payment_id}/verify", headers=a["headers"],
        json={"provider_order_id": "x", "provider_payment_id": "y", "signature": "z"},
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /payments/{id}/retry
# ---------------------------------------------------------------------------


def test_retry_rejects_an_already_paid_payment(client):
    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY, amount=a["order_total"], payment_status=PaymentStatus.PAID)
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 409


def test_retry_rejects_a_cod_payment(client):
    a = _make_customer_with_order(client)
    created = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"}).json()
    response = client.post(f"/api/v1/payments/{created['id']}/retry", headers=a["headers"])
    assert response.status_code == 400


def test_retry_resets_a_failed_payment_back_to_pending(client):
    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(
        order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.FAILED, failure_reason="Signature verification failed",
        razorpay_order_id="order_retry_test",
    )
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


# ---------------------------------------------------------------------------
# Payment Failure Handling (Phase 19) — failure_reason is exposed so the
# client can show a clear, specific state, and clears once a payment is
# retried back to a fresh attempt.
# ---------------------------------------------------------------------------


def test_a_failed_payments_reason_is_exposed_on_get(client):
    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(
        order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.FAILED,
        failure_reason="The amount confirmed by the provider does not match this order's total.",
    )
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.get(f"/api/v1/payments/{payment_id}", headers=a["headers"])
    assert response.status_code == 200
    assert response.json()["failure_reason"] == "The amount confirmed by the provider does not match this order's total."


def test_retry_clears_the_stale_failure_reason(client):
    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(
        order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.FAILED, failure_reason="Payment signature verification failed.",
        razorpay_order_id="order_retry_reason_test",
    )
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 200
    assert response.json()["failure_reason"] is None


def test_customer_a_cannot_retry_customer_bs_payment(client):
    a = _make_customer_with_order(client, tag="a")
    b = _make_customer_with_order(client, tag="b")
    db = _db(client)
    payment = Payment(order_id=UUID(b["order_id"]), user_id=b["customer_id"], provider=PaymentProvider.RAZORPAY, amount=b["order_total"], payment_status=PaymentStatus.FAILED)
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Payment Retry (Phase 20) — retry must also refuse an order that's no
# longer payable, not just a payment that's already PAID. Historical
# PaymentAttempt rows must never be overwritten across a retry cycle.
# ---------------------------------------------------------------------------


def _failed_payment_for(client, a, order_id: str | None = None, order_status: str | None = None):
    from app.models.order import Order, OrderStatus

    db = _db(client)
    if order_status is not None:
        order = db.get(Order, UUID(order_id or a["order_id"]))
        order.status = OrderStatus(order_status)
        db.add(order)
    payment = Payment(
        order_id=UUID(order_id or a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.FAILED, razorpay_order_id="order_phase20_test",
    )
    db.add(payment)
    db.commit()
    payment_id = str(payment.id)
    db.close()
    return payment_id


def test_retry_rejects_a_cancelled_order(client):
    a = _make_customer_with_order(client)
    payment_id = _failed_payment_for(client, a, order_status="cancelled")

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 409
    assert "cancelled" in response.json()["detail"].lower()


def test_retry_rejects_a_rejected_order(client):
    a = _make_customer_with_order(client)
    payment_id = _failed_payment_for(client, a, order_status="rejected")

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 409
    assert "rejected" in response.json()["detail"].lower()


def test_retry_rejects_a_delivered_order(client):
    a = _make_customer_with_order(client)
    payment_id = _failed_payment_for(client, a, order_status="delivered")

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 409
    assert "delivered" in response.json()["detail"].lower()


def test_retry_still_succeeds_for_a_still_payable_order(client):
    """Confirms the new order-status gate isn't over-broad — PLACED
    (and, by the same reasoning, CONFIRMED/PREPARING/etc.) remains
    genuinely retryable."""
    a = _make_customer_with_order(client)
    payment_id = _failed_payment_for(client, a, order_status="placed")

    response = client.post(f"/api/v1/payments/{payment_id}/retry", headers=a["headers"])
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


def test_retry_never_overwrites_historical_payment_attempts(client):
    """A payment can be verified-and-failed, retried, and verified-and-
    failed again — every one of those PaymentAttempt rows must still
    exist afterward, untouched, not merged or overwritten into one row."""
    from app.models.payment_attempt import PaymentAttempt

    a = _make_customer_with_order(client)
    db = _db(client)
    payment = Payment(
        order_id=UUID(a["order_id"]), user_id=a["customer_id"], provider=PaymentProvider.RAZORPAY,
        amount=a["order_total"], payment_status=PaymentStatus.FAILED, razorpay_order_id="order_phase20_history",
    )
    db.add(payment)
    db.commit()
    payment_id = payment.id
    # Two attempts already on record from before this retry — as if two
    # earlier real verification attempts had already failed.
    db.add(PaymentAttempt(
        payment_id=payment_id, provider=PaymentProvider.RAZORPAY, provider_order_id="order_phase20_history",
        provider_payment_id="pay_attempt_1", amount=a["order_total"], status=PaymentStatus.FAILED,
        failure_code="SIGNATURE_MISMATCH", failure_message="first attempt failed",
    ))
    db.add(PaymentAttempt(
        payment_id=payment_id, provider=PaymentProvider.RAZORPAY, provider_order_id="order_phase20_history",
        provider_payment_id="pay_attempt_2", amount=a["order_total"], status=PaymentStatus.FAILED,
        failure_code="AMOUNT_MISMATCH", failure_message="second attempt failed",
    ))
    db.commit()
    payment_id_str = str(payment_id)
    db.close()

    response = client.post(f"/api/v1/payments/{payment_id_str}/retry", headers=a["headers"])
    assert response.status_code == 200

    db2 = _db(client)
    attempts = db2.query(PaymentAttempt).filter(PaymentAttempt.payment_id == payment_id).order_by(PaymentAttempt.provider_payment_id).all()
    assert len(attempts) == 2  # retry itself creates no new attempt row — see payment_service.py's own reasoning
    assert attempts[0].provider_payment_id == "pay_attempt_1"
    assert attempts[0].failure_message == "first attempt failed"  # untouched
    assert attempts[1].provider_payment_id == "pay_attempt_2"
    assert attempts[1].failure_message == "second attempt failed"  # untouched


# ---------------------------------------------------------------------------
# GET /payments/order/{order_id}
# ---------------------------------------------------------------------------


def test_get_payment_by_order_returns_404_before_any_payment_is_created(client):
    a = _make_customer_with_order(client)
    response = client.get(f"/api/v1/payments/order/{a['order_id']}", headers=a["headers"])
    assert response.status_code == 404


def test_get_payment_by_order_returns_the_payment_once_created(client):
    a = _make_customer_with_order(client)
    created = client.post("/api/v1/payments/create", headers=a["headers"], json={"order_id": a["order_id"], "method": "cod"}).json()
    response = client.get(f"/api/v1/payments/order/{a['order_id']}", headers=a["headers"])
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_customer_a_cannot_look_up_customer_bs_order_payment(client):
    a = _make_customer_with_order(client, tag="a")
    b = _make_customer_with_order(client, tag="b")
    client.post("/api/v1/payments/create", headers=b["headers"], json={"order_id": b["order_id"], "method": "cod"})

    blocked = client.get(f"/api/v1/payments/order/{b['order_id']}", headers=a["headers"])
    assert blocked.status_code == 404
