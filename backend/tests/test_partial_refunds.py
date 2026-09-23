"""Payment System Phase 25 — PARTIAL REFUNDS.

Support partial refunds. The exact example this phase names: Order =
₹500, Refund = ₹150, Remaining captured amount = ₹350. Track all
refunds separately. Never overwrite the original payment amount.

This is a verification phase: partial refunds were already fully built
by Refund Architecture (Phase 23) and Razorpay Refund (Phase 24) —
refund_service.create_refund() already accepts any amount up to what
remains refundable, Refund is already an append-only ledger (one row
per refund event, never mutated to represent a different refund), and
nothing anywhere ever assigns Payment.amount after its original capture
(confirmed by a whole-codebase grep). This file proves the phase's own
named example end to end, plus the two properties it calls out by name,
so there's a canonical, explicit test for exactly this phase's own
wording — not just inferred from Phase 23/24's own, differently-worded
tests.
"""

import uuid
from decimal import Decimal

import pytest

from app.core.security import create_access_token, hash_password
from app.db.session import get_db
from app.models.order import Order, OrderStatus
from app.models.payment import Payment, PaymentProvider, PaymentStatus
from app.models.refund import Refund, RefundStatus
from app.models.user import User, UserRole
from app.services.payment import refund_service

ADMIN_PAYMENTS_URL = "/api/v1/admin/payments"


def _db(client):
    return next(client.app.dependency_overrides[get_db]())


def _make_user(db, *, name, email, phone, role):
    user = User(name=name, email=email, phone=phone, password_hash=hash_password("x"), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _admin_headers(db):
    admin = _make_user(db, name="Admin", email=f"admin-p25-{uuid.uuid4().hex[:8]}@example.com", phone=f"81{uuid.uuid4().hex[:8]}", role=UserRole.ADMIN)
    return admin, {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def _make_order_with_paid_payment(db, *, total=Decimal("500.00")):
    order = Order(
        user_id=uuid.uuid4(), customer_name="Cust", customer_email="cust@example.com",
        restaurant_id="rest-1", restaurant_name="Some Restaurant",
        order_number=f"ORD-P25-{uuid.uuid4().hex[:20]}", status=OrderStatus.DELIVERED,
        subtotal=total, delivery_fee=Decimal("0.00"), total=total,
        payment_method="cod", address_line="123 Main St", city="Testville", postal_code="123456",
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    payment = Payment(
        order_id=order.id, user_id=order.user_id, provider=PaymentProvider.COD,
        payment_status=PaymentStatus.PAID, amount=total,
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return order, payment


# ---------------------------------------------------------------------------
# The phase's own named example: Order = 500, Refund = 150, Remaining = 350.
# ---------------------------------------------------------------------------


def test_the_exact_example_this_phase_names(client):
    db = _db(client)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))

    refund = refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), reason="Item missing", provider=None)

    assert refund.amount == Decimal("150.00")
    assert refund.status == RefundStatus.COMPLETED

    db.refresh(payment)
    assert payment.payment_status == PaymentStatus.PARTIALLY_REFUNDED
    # "Remaining captured amount = 350" — the original amount, minus
    # everything genuinely refunded so far, computed fresh, never stored
    # as its own mutable field anywhere.
    refunded_so_far = sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00"))
    remaining = payment.amount - refunded_so_far
    assert refunded_so_far == Decimal("150.00")
    assert remaining == Decimal("350.00")


def test_the_exact_example_via_the_real_admin_http_endpoint(client):
    db = _db(client)
    admin, headers = _admin_headers(db)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))

    response = client.post(
        f"{ADMIN_PAYMENTS_URL}/{payment.id}/refund", headers=headers,
        json={"amount": "150.00", "reason": "Item missing"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PARTIALLY_REFUNDED"
    assert Decimal(body["refunded_amount"]) == Decimal("150.00")
    assert Decimal(body["refundable_amount"]) == Decimal("350.00")
    assert len(body["refunds"]) == 1
    assert Decimal(body["refunds"][0]["amount"]) == Decimal("150.00")


# ---------------------------------------------------------------------------
# "Track all refunds separately."
# ---------------------------------------------------------------------------


def test_multiple_partial_refunds_are_each_tracked_as_their_own_separate_row(client):
    db = _db(client)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))

    first = refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), reason="Damaged item", provider=None)
    second = refund_service.create_refund(db, payment=payment, amount=Decimal("200.00"), reason="Late delivery", provider=None)

    assert first.id != second.id  # two genuinely distinct rows, not one row overwritten

    rows = db.query(Refund).filter(Refund.payment_id == payment.id).order_by(Refund.created_at).all()
    assert len(rows) == 2
    assert [r.amount for r in rows] == [Decimal("150.00"), Decimal("200.00")]
    assert [r.reason for r in rows] == ["Damaged item", "Late delivery"]
    # Each refund keeps its own reason/amount/timestamp — neither
    # overwrites or merges into the other.
    assert rows[0].created_at != rows[1].created_at or rows[0].id != rows[1].id

    db.refresh(payment)
    total_refunded = sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00"))
    assert total_refunded == Decimal("350.00")
    remaining = payment.amount - total_refunded
    assert remaining == Decimal("150.00")
    assert payment.payment_status == PaymentStatus.PARTIALLY_REFUNDED


def test_a_third_refund_can_fully_exhaust_the_remaining_captured_amount(client):
    db = _db(client)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))
    refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), provider=None)
    refund_service.create_refund(db, payment=payment, amount=Decimal("200.00"), provider=None)
    refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), provider=None)

    db.refresh(payment)
    assert db.query(Refund).filter(Refund.payment_id == payment.id).count() == 3
    total_refunded = sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00"))
    assert total_refunded == Decimal("500.00")
    assert payment.payment_status == PaymentStatus.REFUNDED  # fully refunded once it reaches the original amount


# ---------------------------------------------------------------------------
# "Never overwrite the original payment amount."
# ---------------------------------------------------------------------------


def test_payment_amount_is_never_altered_by_any_number_of_partial_refunds(client):
    db = _db(client)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))
    original_amount = payment.amount
    assert original_amount == Decimal("500.00")

    refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), provider=None)
    db.refresh(payment)
    assert payment.amount == original_amount  # untouched by a partial refund

    refund_service.create_refund(db, payment=payment, amount=Decimal("350.00"), provider=None)
    db.refresh(payment)
    assert payment.amount == original_amount  # still untouched, even fully refunded


def test_a_refund_can_never_exceed_the_remaining_captured_amount(client):
    db = _db(client)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))
    refund_service.create_refund(db, payment=payment, amount=Decimal("150.00"), provider=None)

    from app.services.payment.exceptions import RefundError

    with pytest.raises(RefundError):
        # Only 350 remains; asking for one paisa more must be rejected.
        refund_service.create_refund(db, payment=payment, amount=Decimal("350.01"), provider=None)

    db.refresh(payment)
    total_refunded = sum((r.amount for r in payment.refunds if r.status == RefundStatus.COMPLETED), Decimal("0.00"))
    assert total_refunded == Decimal("150.00")  # the rejected attempt left no trace
    assert payment.amount == Decimal("500.00")  # still the original, untouched


def test_admin_refund_audit_log_records_each_partial_refund_separately(client):
    from app.models.admin_audit_log import AdminAuditLog

    db = _db(client)
    admin, headers = _admin_headers(db)
    order, payment = _make_order_with_paid_payment(db, total=Decimal("500.00"))

    client.post(f"{ADMIN_PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "150.00", "reason": "First"})
    client.post(f"{ADMIN_PAYMENTS_URL}/{payment.id}/refund", headers=headers, json={"amount": "200.00", "reason": "Second"})

    logs = db.query(AdminAuditLog).filter(
        AdminAuditLog.target_type == "payment", AdminAuditLog.target_id == str(payment.id), AdminAuditLog.action == "payment.refund",
    ).order_by(AdminAuditLog.created_at).all()
    assert len(logs) == 2
    assert logs[0].reason == "First"
    assert logs[1].reason == "Second"
    # Each entry's own before/after state reflects that specific
    # refund's own contribution, not a merged/overwritten figure.
    assert "refunded=150.00" in logs[0].new_state
    assert "refunded=350.00" in logs[1].new_state
