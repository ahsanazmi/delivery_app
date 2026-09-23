from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Product, Restaurant, User, UserRole
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.services.addresses import create_address
from app.services.cart import add_item, create_cart_for_user
from app.services.orders import create_order
from app.services.payments import list_customer_payments, list_payment_methods, record_order_payment


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    Base.metadata.drop_all(engine)


def _customer(db, email="customer@example.com"):
    user = User(name="Customer", email=email, password_hash="x", role=UserRole.CUSTOMER)
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
        delivery_fee=Decimal("30.00"),
    )
    db.add(restaurant)
    db.commit()
    return restaurant


def _place_order(db, customer, restaurant):
    product = Product(restaurant_id=restaurant.id, name="Item", price=Decimal("100.00"))
    db.add(product)
    db.commit()
    cart = create_cart_for_user(db, customer.id)
    add_item(db, cart, product.id, 1)
    address = create_address(db, customer.id, {
        "label": "Home",
        "recipient_name": "Customer",
        "phone": "9999999999",
        "address_line": "15 Market Road",
        "city": "Bengaluru",
        "state": "Karnataka",
        "postal_code": "560001",
    })
    return create_order(db, customer, address.id)


def test_payment_methods_lists_cod_available_and_online_unavailable_by_default():
    methods = {m["method"]: m for m in list_payment_methods()}
    assert methods["cod"]["available"] is True
    assert methods["online"]["available"] is False


def test_record_order_payment_creates_pending_cod_record(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    result = record_order_payment(db, customer.id, order.id)
    assert result["method"] == "cod"
    assert result["status"] == PaymentStatus.PENDING
    assert result["amount"] == order.total
    assert result["transaction_reference"] is None


def test_record_order_payment_is_idempotent(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    first = record_order_payment(db, customer.id, order.id)
    second = record_order_payment(db, customer.id, order.id)
    assert first["payment_id"] == second["payment_id"]


def test_a_racing_duplicate_insert_is_resolved_to_the_same_row_not_an_error(db, monkeypatch):
    """Integration Phase 12 — reproduces the exact race record_order_payment
    is exposed to: two requests both run their "does a payment already
    exist?" check before either has committed, so both see None and both
    attempt to insert. Forces record_order_payment's own pre-check to
    report None despite a row already existing (exactly what a genuinely
    concurrent transaction would observe), so the test actually exercises
    the IntegrityError-catch-and-recover branch, not just plain idempotency."""
    import app.services.payments as payments_module
    from app.models.payment import Payment, PaymentProvider, PaymentStatus

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    # "Request 1" wins the race and commits first.
    winner = Payment(
        user_id=customer.id, order_id=order.id, amount=order.total,
        provider=PaymentProvider.COD, payment_status=PaymentStatus.PENDING,
    )
    db.add(winner)
    db.commit()

    # Force only the *first* Payment query (record_order_payment's own
    # pre-commit existence check) to miss the row that's actually there —
    # exactly what a genuinely concurrent transaction would observe. The
    # later recovery re-query, after the IntegrityError, must see it for
    # real, so only this one call is faked.
    real_query = db.query
    calls = {"payment_queries": 0}

    def query_that_misses_on_first_call(model, *args, **kwargs):
        if model is Payment:
            calls["payment_queries"] += 1
            if calls["payment_queries"] == 1:
                return real_query(model).filter(Payment.id == None)  # noqa: E711 - deliberately empty
        return real_query(model, *args, **kwargs)

    monkeypatch.setattr(db, "query", query_that_misses_on_first_call)

    result = record_order_payment(db, customer.id, order.id)
    assert result["payment_id"] == winner.id

    monkeypatch.undo()
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1


def test_cannot_record_payment_for_someone_elses_order(db):
    customer = _customer(db)
    other = _customer(db, email="other@example.com")
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    with pytest.raises(HTTPException) as exc_info:
        record_order_payment(db, other.id, order.id)
    assert exc_info.value.status_code == 404


def test_payment_endpoints_over_http():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed)
            restaurant = _restaurant(seed)
            order = _place_order(seed, customer, restaurant)
            order_id = order.id
            from app.core.security import create_access_token

            token = create_access_token(customer.id)

        with TestClient(app) as client:
            headers = {"Authorization": f"Bearer {token}"}

            methods = client.get("/api/v1/customer/payment-methods", headers=headers)
            assert methods.status_code == 200
            by_method = {m["method"]: m for m in methods.json()}
            assert by_method["cod"]["available"] is True
            assert by_method["online"]["available"] is False

            payment = client.post(f"/api/v1/customer/orders/{order_id}/payment", headers=headers)
            assert payment.status_code == 200
            body = payment.json()
            assert body["method"] == "cod"
            assert body["status"] == "pending"
            assert body["transaction_reference"] is None
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)


def test_payment_success_failure_pending_and_retry_on_the_same_record(db, monkeypatch):
    """Integration Phase 12 — the four non-duplicate scenarios in one place:
    a payment starts PENDING, a failed verification attempt (wrong
    signature) leaves it FAILED without marking the order paid, and a
    retried verification with the correct signature on that exact same
    payment row succeeds — proving retry-after-failure works without
    creating a second payment record."""
    import hashlib
    import hmac

    from app.core.config import settings
    from app.models.payment import Payment, PaymentProvider
    from app.services.payments import verify_payment

    customer = _customer(db)
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    payment = Payment(
        user_id=customer.id, order_id=order.id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id="order_retry_test",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    # ---- PENDING (initial state) ----
    assert payment.payment_status == PaymentStatus.PENDING
    assert order.is_paid is False

    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test-secret")

    # ---- FAILURE (wrong signature) ----
    with pytest.raises(HTTPException) as exc_info:
        verify_payment(db, payment=payment, payload={
            "razorpay_order_id": "order_retry_test", "razorpay_payment_id": "pay_retry_test",
            "signature": "not-the-real-signature",
        })
    assert exc_info.value.status_code == 400
    db.refresh(payment)
    db.refresh(order)
    assert payment.payment_status == PaymentStatus.FAILED
    assert order.is_paid is False
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1

    # ---- RETRY (correct signature, same payment row, no new record) ----
    correct_signature = hmac.new(
        b"test-secret", b"order_retry_test|pay_retry_test", hashlib.sha256
    ).hexdigest()
    retried = verify_payment(db, payment=payment, payload={
        "razorpay_order_id": "order_retry_test", "razorpay_payment_id": "pay_retry_test",
        "signature": correct_signature,
    })

    # ---- SUCCESS ----
    assert retried.id == payment.id
    assert retried.payment_status == PaymentStatus.PAID
    db.refresh(order)
    assert order.is_paid is True
    assert order.payment_status == "paid"
    assert db.query(Payment).filter(Payment.order_id == order.id).count() == 1


def test_payment_signature_failure_is_logged_without_the_secret_or_signature(db, monkeypatch, caplog):
    """Logging & Error Handling (Phase 26) — a signature-verification
    failure is a payment error and must reach a server-side log; the
    signature attempted and the RAZORPAY_KEY_SECRET used to check it are
    both on the never-log list and must never appear in that log line."""
    import logging

    from app.core.config import settings
    from app.models.payment import Payment, PaymentProvider
    from app.services.payments import verify_payment

    customer = _customer(db, email="p26-payment@example.com")
    restaurant = _restaurant(db)
    order = _place_order(db, customer, restaurant)

    payment = Payment(
        user_id=customer.id, order_id=order.id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order.total, razorpay_order_id="order_log_test",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    fake_secret = "p26-super-secret-key-must-never-be-logged"
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", fake_secret)
    fake_signature = "p26-fake-signature-must-never-be-logged"

    with caplog.at_level(logging.WARNING):
        with pytest.raises(HTTPException):
            verify_payment(db, payment=payment, payload={
                "razorpay_order_id": "order_log_test", "razorpay_payment_id": "pay_log_test",
                "signature": fake_signature,
            })

    assert any("Payment error" in r.message for r in caplog.records)
    assert fake_secret not in caplog.text
    assert fake_signature not in caplog.text


# ---------------------------------------------------------------------------
# Customer Payment History (Phase 26)
# ---------------------------------------------------------------------------


def test_list_customer_payments_returns_the_expected_fields_newest_first(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    order_a = _place_order(db, customer, restaurant)
    order_b = _place_order(db, customer, restaurant)

    payment_a = Payment(
        user_id=customer.id, order_id=order_a.id, provider=PaymentProvider.COD,
        payment_status=PaymentStatus.PAID, amount=order_a.total,
        created_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    payment_b = Payment(
        user_id=customer.id, order_id=order_b.id, provider=PaymentProvider.RAZORPAY,
        payment_status=PaymentStatus.PENDING, amount=order_b.total, razorpay_order_id="order_p26_1",
        created_at=datetime.now(UTC),
    )
    db.add_all([payment_a, payment_b])
    db.commit()

    results = list_customer_payments(db, customer.id)

    assert [r["payment_id"] for r in results] == [payment_b.id, payment_a.id]  # newest first
    newest = results[0]
    assert newest["order_id"] == order_b.id
    assert newest["order_number"] == order_b.order_number
    assert newest["amount"] == order_b.total
    assert newest["method"] == "online"
    assert newest["status"] == PaymentStatus.PENDING
    oldest = results[1]
    assert oldest["method"] == "cod"
    assert oldest["status"] == PaymentStatus.PAID


def test_list_customer_payments_never_returns_another_customers_payments(db):
    customer = _customer(db, email="p26-mine@example.com")
    other = _customer(db, email="p26-other@example.com")
    restaurant = _restaurant(db)
    mine = _place_order(db, customer, restaurant)
    theirs = _place_order(db, other, restaurant)

    db.add(Payment(user_id=customer.id, order_id=mine.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PENDING, amount=mine.total))
    db.add(Payment(user_id=other.id, order_id=theirs.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PENDING, amount=theirs.total))
    db.commit()

    results = list_customer_payments(db, customer.id)

    assert len(results) == 1
    assert results[0]["order_id"] == mine.id


def test_list_customer_payments_respects_pagination(db):
    customer = _customer(db)
    restaurant = _restaurant(db)
    for i in range(5):
        order = _place_order(db, customer, restaurant)
        db.add(Payment(
            user_id=customer.id, order_id=order.id, provider=PaymentProvider.COD,
            payment_status=PaymentStatus.PENDING, amount=order.total,
            created_at=datetime.now(UTC) - timedelta(minutes=5 - i),
        ))
    db.commit()

    page_one = list_customer_payments(db, customer.id, offset=0, limit=2)
    page_two = list_customer_payments(db, customer.id, offset=2, limit=2)

    assert len(page_one) == 2
    assert len(page_two) == 2
    assert {p["payment_id"] for p in page_one}.isdisjoint({p["payment_id"] for p in page_two})


def test_customer_payment_history_endpoint_over_http_is_scoped_to_the_caller():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as seed:
            customer = _customer(seed, email="p26-http@example.com")
            other = _customer(seed, email="p26-http-other@example.com")
            restaurant = _restaurant(seed)
            mine = _place_order(seed, customer, restaurant)
            theirs = _place_order(seed, other, restaurant)
            seed.add(Payment(user_id=customer.id, order_id=mine.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID, amount=mine.total))
            seed.add(Payment(user_id=other.id, order_id=theirs.id, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID, amount=theirs.total))
            seed.commit()

            from app.core.security import create_access_token
            token = create_access_token(customer.id)
            mine_order_number = mine.order_number

        with TestClient(app) as client:
            response = client.get("/api/v1/customer/payments", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            body = response.json()
            assert len(body) == 1
            assert body[0]["order_number"] == mine_order_number
            assert set(body[0].keys()) >= {
                "payment_id", "order_id", "order_number", "amount", "method", "status", "created_at",
            }

            unauthenticated = client.get("/api/v1/customer/payments")
            assert unauthenticated.status_code in (401, 403)
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)
