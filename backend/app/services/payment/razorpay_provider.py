"""Payment System Phase 4 — the only file in this codebase that knows
Razorpay's specific REST API shape (endpoints, auth scheme, amount units,
response fields). Everything else — PaymentService, RefundService, and
whatever route handlers eventually call them — only ever sees the
provider-agnostic PaymentProvider interface and its ProviderOrder/
ProviderPayment/ProviderRefund dataclasses.

Uses httpx directly against Razorpay's documented REST API
(https://api.razorpay.com/v1) rather than adding the official `razorpay`
SDK as a new dependency — httpx is already a dependency of this project,
and Razorpay's API is small enough that a thin direct client is simpler
than a second HTTP-calling library.
"""

from decimal import ROUND_HALF_UP, Decimal

import httpx

from app.core.config import settings
from app.services.payment.exceptions import ProviderNotConfiguredError, ProviderRequestError
from app.services.payment.provider import PaymentProvider, ProviderOrder, ProviderPayment, ProviderRefund
from app.services.payment.verification import verify_hmac_signature

_API_BASE_URL = "https://api.razorpay.com/v1"


def _to_minor_units(amount: Decimal) -> int:
    """Razorpay amounts are always in the smallest currency unit (paise
    for INR) — 230.00 rupees becomes the integer 23000."""
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _from_minor_units(amount: int) -> Decimal:
    return (Decimal(amount) / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class RazorpayProvider(PaymentProvider):
    name = "razorpay"

    def __init__(
        self,
        *,
        key_id: str | None = None,
        key_secret: str | None = None,
        webhook_secret: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # An explicit override is stored as-is; leaving an argument out
        # means "read app settings fresh on every call," not "read it once
        # now" — Payment System Phase 5's router builds exactly one
        # RazorpayProvider() at import time and keeps it for the process's
        # whole lifetime, so caching settings.RAZORPAY_KEY_SECRET here in
        # __init__ would mean a test (or a real config reload) changing
        # that setting later would silently have no effect on this
        # already-constructed instance.
        self._key_id_override = key_id
        self._key_secret_override = key_secret
        self._webhook_secret_override = webhook_secret
        self._timeout = timeout
        self._transport = transport

    @property
    def _key_id(self) -> str:
        return self._key_id_override if self._key_id_override is not None else settings.RAZORPAY_KEY_ID

    @property
    def _key_secret(self) -> str:
        return self._key_secret_override if self._key_secret_override is not None else settings.RAZORPAY_KEY_SECRET

    @property
    def _webhook_secret(self) -> str:
        if self._webhook_secret_override is not None:
            return self._webhook_secret_override
        return settings.RAZORPAY_WEBHOOK_SECRET

    def _require_credentials(self) -> tuple[str, str]:
        key_id, key_secret = self._key_id, self._key_secret
        if not key_id or not key_secret:
            raise ProviderNotConfiguredError(
                "Razorpay is not configured (RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET missing)."
            )
        return key_id, key_secret

    def _client(self) -> httpx.Client:
        key_id, key_secret = self._require_credentials()
        return httpx.Client(
            base_url=_API_BASE_URL, auth=(key_id, key_secret), timeout=self._timeout, transport=self._transport
        )

    def create_order(
        self, *, amount: Decimal, currency: str = "INR", receipt: str, notes: dict[str, str] | None = None
    ) -> ProviderOrder:
        with self._client() as client:
            try:
                response = client.post(
                    "/orders",
                    json={
                        "amount": _to_minor_units(amount),
                        "currency": currency,
                        "receipt": receipt,
                        "notes": notes or {},
                    },
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderRequestError(f"Razorpay order creation failed: {exc}") from exc

        body = response.json()
        return ProviderOrder(
            provider_order_id=body["id"],
            amount=_from_minor_units(body["amount"]),
            currency=body["currency"],
            status=body["status"],
        )

    def verify_payment_signature(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        _, key_secret = self._require_credentials()
        payload = f"{provider_order_id}|{provider_payment_id}"
        return verify_hmac_signature(payload, signature, key_secret)

    def fetch_payment(self, provider_payment_id: str) -> ProviderPayment:
        with self._client() as client:
            try:
                response = client.get(f"/payments/{provider_payment_id}")
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderRequestError(f"Razorpay payment lookup failed: {exc}") from exc

        body = response.json()
        return ProviderPayment(
            provider_payment_id=body["id"],
            provider_order_id=body.get("order_id"),
            status=body["status"],
            amount=_from_minor_units(body["amount"]),
            currency=body["currency"],
        )

    def fetch_order(self, provider_order_id: str) -> ProviderOrder:
        with self._client() as client:
            try:
                response = client.get(f"/orders/{provider_order_id}")
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderRequestError(f"Razorpay order lookup failed: {exc}") from exc

        body = response.json()
        return ProviderOrder(
            provider_order_id=body["id"],
            amount=_from_minor_units(body["amount"]),
            currency=body["currency"],
            status=body["status"],
        )

    def initiate_refund(
        self, *, provider_payment_id: str, amount: Decimal, notes: dict[str, str] | None = None
    ) -> ProviderRefund:
        with self._client() as client:
            try:
                response = client.post(
                    f"/payments/{provider_payment_id}/refund",
                    json={"amount": _to_minor_units(amount), "notes": notes or {}},
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ProviderRequestError(f"Razorpay refund failed: {exc}") from exc

        body = response.json()
        return ProviderRefund(
            provider_refund_id=body["id"], status=body["status"], amount=_from_minor_units(body["amount"])
        )

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        if not self._webhook_secret:
            raise ProviderNotConfiguredError("Razorpay webhook secret is not configured.")
        return verify_hmac_signature(payload.decode("utf-8"), signature, self._webhook_secret)
