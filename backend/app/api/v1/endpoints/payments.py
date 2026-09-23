from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from app.api.v1.deps import DbSession, require_customer
from app.core.config import settings
from app.models.order import Order
from app.models.payment import Payment
from app.models.payment import PaymentProvider as PaymentProviderEnum
from app.models.payment import PaymentStatus
from app.models.user import User
from app.schemas.payment import PaymentCreateRequest, PaymentResponse, PaymentVerifyRequest
from app.services.payment.exceptions import (
    PaymentError,
    PaymentExpiredError,
    PaymentVerificationError,
    ProviderNotConfiguredError,
    ProviderRequestError,
)
from app.services.payment.payment_service import PaymentService
from app.services.payment.verification import verify_hmac_signature
from app.services.payment.webhook_service import process_webhook_event

router = APIRouter()

# Payment System Phase 5 — one PaymentService instance for this router's
# whole lifetime. Its own constructor never touches the network (see
# RazorpayProvider's own lazy-credential-check design from Phase 4), so
# building it once at import time — the same pattern every other
# module-level `router = APIRouter()` in this codebase already uses — is
# safe even before RAZORPAY_KEY_ID/SECRET are configured.
_payment_service = PaymentService()

# A payment can be (re)verified from any of these — PENDING (never tried),
# PROCESSING (attempted, still waiting), or FAILED (a previous attempt was
# rejected, e.g. by /verify itself). Once PAID it is terminal for this
# endpoint — verifying an already-PAID payment again is exactly the replay
# scenario Phase 3's provider-id uniqueness constraints exist to catch at
# the database layer; rejecting it here too gives a clean 409 instead of
# letting that request reach the database at all.
_VERIFIABLE_STATUSES = (PaymentStatus.PENDING, PaymentStatus.PROCESSING, PaymentStatus.FAILED)
_RETRYABLE_STATUSES = (PaymentStatus.PENDING, PaymentStatus.FAILED)


def _to_payment_response(payment: Payment) -> PaymentResponse:
    return PaymentResponse(
        id=payment.id,
        order_id=payment.order_id,
        method="cod" if payment.provider == PaymentProviderEnum.COD else "razorpay",
        status=payment.payment_status,
        amount=payment.amount,
        currency=payment.currency,
        provider_order_id=payment.razorpay_order_id,
        provider_payment_id=payment.razorpay_payment_id,
        is_verified=payment.is_verified,
        paid_at=payment.paid_at,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        # Razorpay Order Creation (Phase 12) — see app/services/payments.py's
        # _to_customer_payment for the same reasoning.
        razorpay_key_id=(settings.RAZORPAY_KEY_ID or None) if payment.provider == PaymentProviderEnum.RAZORPAY else None,
        failure_reason=payment.failure_reason,
    )


def _get_owned_order_or_404(db: DbSession, order_id: UUID, current_user: User) -> Order:
    # Never leak whether an order id exists at all to someone who doesn't
    # own it — same 404-not-403 convention this codebase uses everywhere
    # else for cross-account access (see Phase 22's own IDOR sweep).
    order = db.get(Order, order_id)
    if not order or order.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


def _get_owned_payment_or_404(db: DbSession, payment_id: UUID, current_user: User) -> Payment:
    payment = db.get(Payment, payment_id)
    if not payment or payment.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


@router.post("/create", response_model=PaymentResponse, status_code=status.HTTP_201_CREATED)
def create_payment(
    payload: PaymentCreateRequest, db: DbSession, current_user: User = Depends(require_customer)
) -> PaymentResponse:
    """Authenticate: require_customer. Order ownership: _get_owned_order_or_404.
    Payment state: PaymentService.create_payment_for_order is idempotent —
    an existing Payment for this order is returned rather than a duplicate
    being created. Amount: always order.total, never accepted here."""
    order = _get_owned_order_or_404(db, payload.order_id, current_user)

    try:
        payment = _payment_service.create_payment_for_order(db, order=order, method=payload.method)
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach the payment provider right now."
        ) from exc
    return _to_payment_response(payment)


@router.get("/order/{order_id}", response_model=PaymentResponse)
def get_payment_by_order(
    order_id: UUID, db: DbSession, current_user: User = Depends(require_customer)
) -> PaymentResponse:
    """Authenticate: require_customer. Order ownership: _get_owned_order_or_404
    (checked before the payment lookup even happens, so a customer can
    never learn whether *any* payment exists for an order that isn't
    theirs). Payment state: 404 if none exists yet, rather than a null
    body the client has to special-case."""
    order = _get_owned_order_or_404(db, order_id, current_user)
    payment = _payment_service.get_payment_for_order(db, order.id)
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No payment exists for this order yet")
    return _to_payment_response(payment)


@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment(payment_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> PaymentResponse:
    """Authenticate: require_customer. Order ownership: enforced via
    Payment.user_id (the payment's own order was already confirmed to
    belong to this same user at creation time — see create_payment above
    and uq_payments_order_id) — Customer A gets a 404, not another
    customer's payment, the moment payment.user_id doesn't match."""
    payment = _get_owned_payment_or_404(db, payment_id, current_user)
    return _to_payment_response(payment)


@router.post("/{payment_id}/verify", response_model=PaymentResponse)
def verify_payment_endpoint(
    payment_id: UUID, payload: PaymentVerifyRequest, db: DbSession, current_user: User = Depends(require_customer)
) -> PaymentResponse:
    """Authenticate: require_customer. Order ownership: _get_owned_payment_or_404.
    Payment state: rejects anything not in _VERIFIABLE_STATUSES (most
    importantly, an already-PAID payment) before ever calling the
    provider. Amount: never in the request body at all — verification is
    a signature check against ids, not a value the client can influence."""
    payment = _get_owned_payment_or_404(db, payment_id, current_user)

    if payment.provider != PaymentProviderEnum.RAZORPAY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This payment is Cash on Delivery and cannot be verified online.",
        )
    if payment.payment_status not in _VERIFIABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot verify a payment already in status '{payment.payment_status.value}'.",
        )

    try:
        verified = _payment_service.verify_payment(
            db, payment=payment, provider_order_id=payload.provider_order_id,
            provider_payment_id=payload.provider_payment_id, signature=payload.signature,
        )
    except PaymentExpiredError as exc:
        # Payment Failure & Recovery Testing (Phase 32) — a closed
        # checkout window, not a rejection. 410 Gone: the resource (this
        # payment's chance to be verified) genuinely no longer exists,
        # distinct from every other 4xx this endpoint returns.
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except PaymentVerificationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payment verification failed") from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ProviderRequestError as exc:
        # Payment Failure & Recovery Testing (Phase 32) — distinct from a
        # genuine PaymentVerificationError: the provider was momentarily
        # unreachable, not confirmed-rejecting. The payment itself was
        # left untouched (see verify_payment()'s own handling), so the
        # honest response is "try again", the same 502 create_payment
        # already gives for the identical underlying exception.
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Unable to reach the payment provider right now."
        ) from exc
    return _to_payment_response(verified)


@router.post("/{payment_id}/retry", response_model=PaymentResponse)
def retry_payment(payment_id: UUID, db: DbSession, current_user: User = Depends(require_customer)) -> PaymentResponse:
    """Authenticate: require_customer. Order ownership: _get_owned_payment_or_404.
    Payment state: only PENDING/FAILED may be retried — an already-PAID
    payment has nothing to retry, and retrying it would be the same
    double-charge risk this whole payment system is built to prevent.
    Amount: unchanged — a retry reopens the same provider order at the
    same amount, it never lets the client renegotiate the price."""
    payment = _get_owned_payment_or_404(db, payment_id, current_user)

    if payment.provider != PaymentProviderEnum.RAZORPAY:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cash on Delivery payments cannot be retried online.")
    if payment.payment_status not in _RETRYABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry a payment in status '{payment.payment_status.value}'.",
        )

    try:
        retried = _payment_service.retry_payment(db, payment=payment)
    except PaymentExpiredError as exc:
        # Payment Failure & Recovery Testing (Phase 32) — see the
        # /verify endpoint's own note on the same exception.
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=str(exc)) from exc
    except PaymentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_payment_response(retried)


# ---------------------------------------------------------------------------
# Refund Architecture (Phase 23) — the legacy customer-facing refund
# endpoint that used to live here (unguarded — any customer could call it
# for their own payment, flagged as a known gap since Phase 1's own audit)
# has been retired. A customer never self-serves a refund in this system;
# refunds are now exclusively an admin action —
# POST /api/v1/admin/payments/{id}/refund (see app/api/v1/admin/payments.py
# and app/services/admin_payments.py::admin_refund_payment), which goes
# through the real, validated app/services/payment/refund_service.py this
# old endpoint never actually used. Confirmed via grep that no frontend
# (customer-mobile/rider-mobile/business-web/admin-web) ever called this
# old route before removing it.
# ---------------------------------------------------------------------------


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(request: Request, db: DbSession, background_tasks: BackgroundTasks) -> dict[str, str]:
    """Payment Webhooks (Phase 17) / Webhook Idempotency (Phase 18) —
    receives a Razorpay event, verifies its signature before trusting
    anything in it (Phase 5's own original authenticity check, unchanged),
    then hands the verified body — along with Razorpay's own
    x-razorpay-event-id header, its documented mechanism for identifying
    duplicate deliveries — to process_webhook_event() to identify the
    payment/order, apply the event idempotently, and record an audit row
    for it either way.

    Never a 4xx for an event this backend simply doesn't act on (an
    unrecognized event type, or one whose payment/refund can't be found)
    — those are legitimate, recorded outcomes, not request errors; a 4xx
    is reserved for a request that isn't genuinely from Razorpay at all,
    since Razorpay retries on anything but a 200 and a real, well-formed
    event should never be endlessly redelivered just because this backend
    doesn't happen to act on it.

    Performance & Reliability (Phase 39) — background_tasks is threaded
    through to process_webhook_event() so any admin push notification a
    handler triggers (e.g. the dead-order/needs-reconciliation alert) is
    sent *after* this response, never blocking Razorpay's own ack on a
    slow or unreachable Expo push endpoint."""
    signature = request.headers.get("x-razorpay-signature")
    if not signature:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing Razorpay signature")

    if not settings.RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook verification is not configured yet."
        )

    body = await request.body()
    if not verify_hmac_signature(body.decode("utf-8"), signature, settings.RAZORPAY_WEBHOOK_SECRET):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature")

    event_id = request.headers.get("x-razorpay-event-id")
    process_webhook_event(db, raw_body=body, event_id=event_id, background_tasks=background_tasks)
    return {"status": "received"}
