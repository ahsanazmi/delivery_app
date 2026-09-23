from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.payment import PaymentProvider, PaymentStatus


class PaymentCreate(BaseModel):
    # Deliberately no `amount` field — the amount is always derived from the
    # order's own server-computed total (see create_payment), never accepted
    # from the client.
    order_id: UUID
    currency: str = "INR"
    provider: PaymentProvider = PaymentProvider.RAZORPAY


class PaymentVerify(BaseModel):
    payment_id: str | None = None
    order_id: UUID | None = None
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None
    signature: str | None = None


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    user_id: UUID
    provider: PaymentProvider
    payment_status: PaymentStatus
    amount: Decimal
    currency: str
    razorpay_order_id: str | None
    razorpay_payment_id: str | None
    is_verified: bool
    failure_reason: str | None
    refund_id: str | None
    refund_status: str | None
    created_at: datetime
    updated_at: datetime


class PaymentMethodOption(BaseModel):
    """A payment method the customer app can offer at checkout — a stable,
    generic contract that doesn't leak which specific gateway backs it, so a
    future Razorpay (or any other online provider) integration slots in behind
    `method: "online"` without changing this shape."""

    method: Literal["cod", "online"]
    label: str
    available: bool


class CustomerPaymentRead(BaseModel):
    payment_id: UUID
    order_id: UUID
    # Customer Payment History (Phase 26) — the order's own human-readable
    # reference (e.g. "ORD-000123"), so the app never has to show a raw
    # UUID to the customer.
    order_number: str
    amount: Decimal
    method: Literal["cod", "online"]
    status: PaymentStatus
    transaction_reference: str | None
    created_at: datetime
    updated_at: datetime
    # Razorpay Order Creation (Phase 12) — the public key_id the mobile
    # app's Razorpay Checkout SDK needs to actually open the payment sheet
    # for this order. Safe to return: key_id is Razorpay's own public
    # identifier, distinct from RAZORPAY_KEY_SECRET, which this response
    # (and every payment response in this codebase) never includes. None
    # for COD, since there's no checkout sheet to open.
    razorpay_key_id: str | None = None


# --- Payment System Phase 5 — /api/v1/payments/* -----------------------
# Deliberately separate from PaymentCreate/PaymentVerify/PaymentRead above
# (the pre-Phase-4 shapes, still used by the untouched webhook/refund
# endpoints in this same router): provider-agnostic field names
# (method/status/provider_order_id, never razorpay_*), and never a
# user_id or signature in the response — see this phase's own "safe
# response" requirement.


class PaymentCreateRequest(BaseModel):
    order_id: UUID
    # A real, legitimate customer choice (cod vs. paying online) — never
    # which concrete provider class handles "online"; that mapping is
    # entirely PaymentService's own, server-side decision.
    method: Literal["cod", "razorpay"]


class PaymentVerifyRequest(BaseModel):
    provider_order_id: str
    provider_payment_id: str
    signature: str


class PaymentResponse(BaseModel):
    id: UUID
    order_id: UUID
    method: Literal["cod", "razorpay"]
    status: PaymentStatus
    amount: Decimal
    currency: str
    provider_order_id: str | None
    provider_payment_id: str | None
    is_verified: bool
    paid_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Razorpay Order Creation (Phase 12) — see CustomerPaymentRead's own
    # note above; same field, same reasoning, for this router's response.
    razorpay_key_id: str | None = None
    # Payment Failure Handling (Phase 19) — the specific reason the last
    # verification attempt failed (e.g. "Payment signature verification
    # failed.", "The amount confirmed by the provider does not match this
    # order's total."), so the client can show something more useful than
    # a bare "failed" status. None whenever status isn't "failed".
    failure_reason: str | None = None
