"""Admin Portal — Phase 13: Payment Management (view-only)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.user import User, UserRole

PAYMENTS_URL = "/api/v1/admin/payments"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p13-{uuid.uuid4().hex[:8]}@example.com", phone=f"84{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_order(db, *, status=OrderStatus.DELIVERED, customer_name="Cust", order_number=None):
    order = Order(
        user_id=uuid.uuid4(), customer_name=customer_name, customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=order_number or f"ORD-{uuid.uuid4().hex[:20]}", status=status,
        subtotal=Decimal("100.00"), delivery_fee=Decimal("30.00"), total=Decimal("130.00"),
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


def _make_payment(db, *, order, provider=PaymentProvider.COD, payment_status=PaymentStatus.PENDING, **extra):
    payment = Payment(
        order_id=order.id, user_id=uuid.uuid4(), provider=provider, payment_status=payment_status,
        amount=order.total, **extra,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment


def test_list_requires_admin(client):
    db = _db(client)
    customer = _make_user(db, name="Not Admin", email="not-admin-p13@example.com", phone="8400000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)
    assert client.get(PAYMENTS_URL, headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get(PAYMENTS_URL).status_code == 401


def test_list_returns_summary_fields(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db, customer_name="Alice", order_number="ORD-P13-001")
    payment = _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PAID,
        razorpay_payment_id="pay_abc123",
    )

    response = client.get(PAYMENTS_URL, headers=headers)
    assert response.status_code == 200
    match = next(item for item in response.json()["items"] if item["id"] == str(payment.id))
    assert match["order_number"] == "ORD-P13-001"
    assert match["customer_name"] == "Alice"
    assert match["method"] == "razorpay"
    assert match["status"] == "PAID"
    assert match["transaction_reference"] == "pay_abc123"
    assert Decimal(match["amount"]) == order.total


def test_list_includes_provider_paid_at_and_latest_refund_status(client):
    """Admin Payment Management (Phase 27) — the three fields this phase
    added to the list view (previously either missing entirely or only
    present on the detail response)."""
    db = _db(client)
    _, headers = _admin_headers(db)

    cod_order = _make_order(db, customer_name="COD Customer")
    cod_payment = _make_payment(db, order=cod_order, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID)

    online_order = _make_order(db, customer_name="Online Customer")
    paid_at = datetime.now(UTC)
    online_payment = _make_payment(
        db, order=online_order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PAID,
        razorpay_payment_id="pay_p27_1", paid_at=paid_at,
    )

    response = client.get(PAYMENTS_URL, headers=headers)
    items = {item["id"]: item for item in response.json()["items"]}

    cod_item = items[str(cod_payment.id)]
    assert cod_item["provider"] is None  # cash has no external provider
    assert cod_item["latest_refund_status"] is None  # never refunded

    online_item = items[str(online_payment.id)]
    assert online_item["provider"] == "Razorpay"
    assert online_item["paid_at"] is not None
    assert online_item["latest_refund_status"] is None


def test_list_and_detail_reflect_the_real_latest_refund_status(client):
    """Admin Payment Management (Phase 27) — replaces the old, always-null
    Payment.refund_status column (never written to by any code path) with
    the real, most-recent Refund row's own status, on both the list and
    the detail response."""
    from app.models.refund import Refund, RefundStatus

    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PARTIALLY_REFUNDED,
        razorpay_payment_id="pay_p27_2",
    )
    db.add(Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("30.00"), status=RefundStatus.COMPLETED))
    db.commit()
    second_refund = Refund(payment_id=payment.id, order_id=order.id, amount=Decimal("20.00"), status=RefundStatus.PROCESSING)
    db.add(second_refund)
    db.commit()
    db.refresh(second_refund)
    # Force the second refund to be the most recent by creation time,
    # independent of insertion order/timestamp resolution.
    db.query(Refund).filter(Refund.id == second_refund.id).update(
        {Refund.created_at: datetime.now(UTC) + timedelta(minutes=5)}
    )
    db.commit()

    listed = client.get(PAYMENTS_URL, headers=headers)
    match = next(item for item in listed.json()["items"] if item["id"] == str(payment.id))
    assert match["latest_refund_status"] == "processing"

    detail = client.get(f"{PAYMENTS_URL}/{payment.id}", headers=headers)
    assert detail.json()["latest_refund_status"] == "processing"


def test_order_id_and_customer_filters(client):
    """Admin Payment Management (Phase 27) — the two new, dedicated
    filters, additive alongside the existing combined `search`."""
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db, customer_name="Filter Target", order_number="ORD-P27-FILTER")
    payment = _make_payment(db, order=order)
    _make_order(db, customer_name="Someone Else", order_number="ORD-P27-OTHER")

    by_order = client.get(PAYMENTS_URL, headers=headers, params={"order_number": "P27-FILTER"})
    assert [i["id"] for i in by_order.json()["items"]] == [str(payment.id)]

    by_customer = client.get(PAYMENTS_URL, headers=headers, params={"customer": "Filter Target"})
    assert [i["id"] for i in by_customer.json()["items"]] == [str(payment.id)]

    no_match = client.get(PAYMENTS_URL, headers=headers, params={"order_number": "does-not-exist"})
    assert no_match.json()["items"] == []


def test_list_never_exposes_signature_or_raw_razorpay_ids_separately(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PAID,
        razorpay_order_id="order_xyz", razorpay_payment_id="pay_xyz", razorpay_signature="super-secret-signature",
    )

    response = client.get(PAYMENTS_URL, headers=headers)
    raw_text = response.text
    assert "super-secret-signature" not in raw_text
    assert "razorpay_signature" not in raw_text
    assert "razorpay_order_id" not in raw_text
    assert "razorpay_payment_id" not in raw_text


def test_detail_never_exposes_signature(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PAID,
        razorpay_signature="super-secret-signature-2",
    )

    response = client.get(f"{PAYMENTS_URL}/{payment.id}", headers=headers)
    assert "super-secret-signature-2" not in response.text
    assert "razorpay_signature" not in response.text


def test_cancelled_order_with_pending_payment_shows_as_cancelled(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db, status=OrderStatus.CANCELLED)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PENDING)

    response = client.get(f"{PAYMENTS_URL}/{payment.id}", headers=headers)
    assert response.json()["status"] == "CANCELLED"


def test_status_filter_cancelled_returns_only_pending_payments_on_cancelled_orders(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    cancelled_order = _make_order(db, status=OrderStatus.CANCELLED)
    cancelled_payment = _make_payment(db, order=cancelled_order, payment_status=PaymentStatus.PENDING)
    active_order = _make_order(db, status=OrderStatus.PREPARING)
    _make_payment(db, order=active_order, payment_status=PaymentStatus.PENDING)

    response = client.get(PAYMENTS_URL, headers=headers, params={"status": "CANCELLED"})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(cancelled_payment.id)]


def test_status_filter_pending_excludes_cancelled_orders(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    cancelled_order = _make_order(db, status=OrderStatus.CANCELLED)
    _make_payment(db, order=cancelled_order, payment_status=PaymentStatus.PENDING)
    active_order = _make_order(db, status=OrderStatus.PREPARING)
    active_payment = _make_payment(db, order=active_order, payment_status=PaymentStatus.PENDING)

    response = client.get(PAYMENTS_URL, headers=headers, params={"status": "PENDING"})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(active_payment.id)]


def test_failed_status_is_listed_filterable_and_shows_failure_reason_in_detail(client):
    """Admin Portal Phase 31 — the one PaymentStatus value none of Phase
    13's own tests ever exercised (PENDING/PAID/REFUND_PENDING/REFUNDED/the
    synthesized CANCELLED all were, FAILED wasn't)."""
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db, status=OrderStatus.PLACED)
    failed_payment = _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.FAILED,
        failure_reason="Signature verification failed",
    )
    other_order = _make_order(db)
    _make_payment(db, order=other_order, provider=PaymentProvider.COD, payment_status=PaymentStatus.PENDING)

    listed = client.get(PAYMENTS_URL, headers=headers, params={"status": "FAILED"})
    assert listed.status_code == 200
    ids = [item["id"] for item in listed.json()["items"]]
    assert ids == [str(failed_payment.id)]
    assert listed.json()["items"][0]["status"] == "FAILED"

    detail = client.get(f"{PAYMENTS_URL}/{failed_payment.id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "FAILED"
    assert detail.json()["failure_reason"] == "Signature verification failed"


def test_status_filter_covers_processing_and_partially_refunded(client):
    """Admin Payment Management (Phase 27) — PaymentStatus.PROCESSING and
    PARTIALLY_REFUNDED (added to AdminPaymentStatusValue back in Phase 23)
    were filterable at the backend but never selectable in admin-web's own
    STATUS_OPTIONS list, so this backend guarantee is the half of the fix
    admin-web's own test suite can't cover."""
    db = _db(client)
    _, headers = _admin_headers(db)
    processing_order = _make_order(db)
    processing_payment = _make_payment(db, order=processing_order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PROCESSING)
    partial_order = _make_order(db)
    partial_payment = _make_payment(db, order=partial_order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PARTIALLY_REFUNDED)

    processing_response = client.get(PAYMENTS_URL, headers=headers, params={"status": "PROCESSING"})
    assert [i["id"] for i in processing_response.json()["items"]] == [str(processing_payment.id)]

    partial_response = client.get(PAYMENTS_URL, headers=headers, params={"status": "PARTIALLY_REFUNDED"})
    assert [i["id"] for i in partial_response.json()["items"]] == [str(partial_payment.id)]


def test_method_filter(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    cod_order = _make_order(db)
    cod_payment = _make_payment(db, order=cod_order, provider=PaymentProvider.COD)
    online_order = _make_order(db)
    _make_payment(db, order=online_order, provider=PaymentProvider.RAZORPAY)

    response = client.get(PAYMENTS_URL, headers=headers, params={"method": "cod"})
    ids = [item["id"] for item in response.json()["items"]]
    assert ids == [str(cod_payment.id)]


def test_search_matches_order_number_customer_and_transaction_reference(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db, customer_name="Findable Customer", order_number="ORD-FINDME-P13")
    payment = _make_payment(db, order=order, provider=PaymentProvider.RAZORPAY, razorpay_payment_id="pay_findable_ref")
    _make_order(db, customer_name="Other Customer")

    r1 = client.get(PAYMENTS_URL, headers=headers, params={"search": "FINDME"})
    assert [i["id"] for i in r1.json()["items"]] == [str(payment.id)]

    r2 = client.get(PAYMENTS_URL, headers=headers, params={"search": "Findable Customer"})
    assert [i["id"] for i in r2.json()["items"]] == [str(payment.id)]

    r3 = client.get(PAYMENTS_URL, headers=headers, params={"search": "pay_findable_ref"})
    assert [i["id"] for i in r3.json()["items"]] == [str(payment.id)]


def test_date_range_filter(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    old_order = _make_order(db)
    old_payment = _make_payment(db, order=old_order)
    db.query(Payment).filter(Payment.id == old_payment.id).update({Payment.created_at: datetime.now(UTC) - timedelta(days=10)})
    db.commit()
    new_order = _make_order(db)
    new_payment = _make_payment(db, order=new_order)

    cutoff = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    response = client.get(PAYMENTS_URL, headers=headers, params={"date_from": cutoff})
    ids = [item["id"] for item in response.json()["items"]]
    assert str(new_payment.id) in ids
    assert str(old_payment.id) not in ids


def test_pagination(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    for _ in range(3):
        order = _make_order(db)
        _make_payment(db, order=order)

    response = client.get(PAYMENTS_URL, headers=headers, params={"page": 1, "limit": 2})
    body = response.json()
    assert body["total"] >= 3
    assert len(body["items"]) == 2


def test_detail_includes_cod_collection_info(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    rider = _make_user(db, name="Collecting Rider", email="collecting-rider-p13@example.com", phone="8400000010", role=UserRole.RIDER)
    order = _make_order(db, status=OrderStatus.DELIVERED)
    now = datetime.now(UTC)
    payment = _make_payment(
        db, order=order, provider=PaymentProvider.COD, payment_status=PaymentStatus.PAID,
        collected_by_rider_id=rider.id, collected_at=now,
    )

    response = client.get(f"{PAYMENTS_URL}/{payment.id}", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["collected_by_rider_name"] == "Collecting Rider"
    assert body["collected_at"] is not None
    assert body["customer_email"] == "cust@example.com"


def test_detail_404_for_missing_payment(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    response = client.get(f"{PAYMENTS_URL}/00000000-0000-0000-0000-000000000000", headers=headers)
    assert response.status_code == 404


def test_detail_requires_admin(client):
    db = _db(client)
    order = _make_order(db)
    payment = _make_payment(db, order=order)
    customer = _make_user(db, name="Peeker", email="peeker-p13@example.com", phone="8400000020", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)

    response = client.get(f"{PAYMENTS_URL}/{payment.id}", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


def test_refund_pending_status_is_visible(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.REFUND_PENDING)

    response = client.get(f"{PAYMENTS_URL}/{payment.id}", headers=headers)
    assert response.json()["status"] == "REFUND_PENDING"


# ---------------------------------------------------------------------------
# Refund Architecture (Phase 23) — POST /admin/payments/{id}/refund
# ---------------------------------------------------------------------------


def test_refund_requires_admin(client):
    db = _db(client)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)
    customer = _make_user(db, name="Not Admin", email="not-admin-p23@example.com", phone="8500000001", role=UserRole.CUSTOMER)
    token = create_access_token(customer.id)

    response = client.post(
        f"{PAYMENTS_URL}/{payment.id}/refund", headers={"Authorization": f"Bearer {token}"},
        json={"amount": "50.00", "reason": "test"},
    )
    assert response.status_code == 403


def test_refund_requires_a_reason(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "50.00", "reason": ""})
    assert response.status_code == 422


def test_full_cod_refund_updates_payment_status_and_ledger(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)  # order.total = 130.00

    response = client.post(
        f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "130.00", "reason": "Customer complaint"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "REFUNDED"
    assert body["refunded_amount"] == "130.00"
    assert body["refundable_amount"] == "0.00"
    assert len(body["refunds"]) == 1
    assert body["refunds"][0]["reason"] == "Customer complaint"
    assert body["refunds"][0]["status"] == "completed"


def test_partial_refund_leaves_payment_partially_refunded(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "30.00", "reason": "Missing item"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIALLY_REFUNDED"
    assert body["refunded_amount"] == "30.00"
    assert body["refundable_amount"] == "100.00"


def test_refund_cannot_exceed_the_refundable_amount(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)  # total = 130.00

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "200.00", "reason": "test"})
    assert response.status_code == 409


def test_refund_cannot_exceed_what_remains_after_a_previous_refund(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)

    first = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "100.00", "reason": "first"})
    assert first.status_code == 200
    assert first.json()["status"] == "PARTIALLY_REFUNDED"

    second = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "31.00", "reason": "too much"})
    assert second.status_code == 409  # only 30.00 remains

    third = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "30.00", "reason": "the rest"})
    assert third.status_code == 200
    assert third.json()["status"] == "REFUNDED"
    assert len(third.json()["refunds"]) == 2  # both refunds survive, never merged/overwritten


def test_refund_rejects_a_payment_that_was_never_paid(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PENDING)

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "10.00", "reason": "test"})
    assert response.status_code == 409


def test_refund_404_for_missing_payment(client):
    db = _db(client)
    _, headers = _admin_headers(db)
    response = client.post(
        f"{PAYMENTS_URL}/00000000-0000-0000-0000-000000000000/refund", headers=headers,
        json={"amount": "10.00", "reason": "test"},
    )
    assert response.status_code == 404


def test_refund_is_recorded_in_the_admin_audit_log(client):
    from app.models.admin_audit_log import AdminAuditLog

    db = _db(client)
    admin, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(db, order=order, payment_status=PaymentStatus.PAID)

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "50.00", "reason": "Audit check"})
    assert response.status_code == 200

    entries = db.query(AdminAuditLog).filter(AdminAuditLog.action == "payment.refund", AdminAuditLog.target_id == str(payment.id)).all()
    assert len(entries) == 1
    assert entries[0].admin_id == admin.id
    assert entries[0].reason == "Audit check"
    assert order.status.value in entries[0].previous_state


def test_online_refund_calls_the_real_provider(client, monkeypatch):
    """Confirms the online (razorpay) branch is genuinely wired to the
    provider, not just the COD short-circuit exercised by every other
    test in this file."""
    from app.services.payment.provider import PaymentProvider as ProviderABC
    from app.services.payment.provider import ProviderRefund

    class FakeRazorpayProvider(ProviderABC):
        name = "fake"
        calls: list[dict] = []

        def create_order(self, *, amount, currency, receipt, notes=None):
            raise NotImplementedError

        def verify_payment_signature(self, *, provider_order_id, provider_payment_id, signature):
            raise NotImplementedError

        def fetch_payment(self, provider_payment_id):
            raise NotImplementedError

        def fetch_order(self, provider_order_id):
            raise NotImplementedError

        def initiate_refund(self, *, provider_payment_id, amount, notes=None):
            FakeRazorpayProvider.calls.append({"provider_payment_id": provider_payment_id, "amount": amount})
            return ProviderRefund(provider_refund_id="rfnd_p23_live", status="processed", amount=amount)

        def verify_webhook_signature(self, *, payload, signature):
            raise NotImplementedError

    monkeypatch.setattr("app.services.payment.payment_service.RazorpayProvider", lambda *a, **k: FakeRazorpayProvider())

    db = _db(client)
    _, headers = _admin_headers(db)
    order = _make_order(db)
    payment = _make_payment(
        db, order=order, provider=PaymentProvider.RAZORPAY, payment_status=PaymentStatus.PAID,
        razorpay_payment_id="pay_p23_real",
    )

    response = client.post(f"{PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "50.00", "reason": "online refund"})
    assert response.status_code == 200
    assert response.json()["refunds"][0]["provider_refund_id"] == "rfnd_p23_live"
    assert len(FakeRazorpayProvider.calls) == 1
    assert FakeRazorpayProvider.calls[0]["provider_payment_id"] == "pay_p23_real"
