"""Payment System Phase 4 — the PaymentProvider interface every concrete
gateway (RazorpayProvider today, anything else later) implements. Nothing
outside this package should ever import a concrete provider directly —
PaymentService is the only caller, exactly so a future second provider
slots in here without any other code changing.

The three dataclasses below are this package's own provider-agnostic
vocabulary for what a gateway hands back — never the provider's own raw
response dict, so RazorpayProvider is the only place that has to know
Razorpay's specific JSON shape.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ProviderOrder:
    provider_order_id: str
    amount: Decimal
    currency: str
    status: str


@dataclass(frozen=True)
class ProviderPayment:
    provider_payment_id: str
    provider_order_id: str | None
    status: str
    amount: Decimal
    # Payment Amount Validation (Phase 15) — currency was silently dropped
    # on the floor before this phase; a Razorpay account/order misconfigured
    # to a different currency than this platform expects would otherwise
    # pass every other check (amount, order id, signature) while actually
    # settling the wrong number of actual rupees/whatever the mismatch is.
    currency: str


@dataclass(frozen=True)
class ProviderRefund:
    provider_refund_id: str
    status: str
    amount: Decimal


class PaymentProvider(ABC):
    """Cash on Delivery deliberately has no provider class of its own —
    there is no external gateway to call for COD, so PaymentService
    handles it directly rather than forcing a trivial no-op
    implementation of this interface to exist just for symmetry."""

    name: str

    @abstractmethod
    def create_order(
        self, *, amount: Decimal, currency: str, receipt: str, notes: dict[str, str] | None = None
    ) -> ProviderOrder:
        """Open a new payment intent at the provider for this amount.
        `receipt` is our own reference (this codebase always passes the
        platform order id) so the provider's own dashboard can be
        cross-referenced back to a real order."""

    @abstractmethod
    def verify_payment_signature(
        self, *, provider_order_id: str, provider_payment_id: str, signature: str
    ) -> bool:
        """True only if `signature` is a genuine, cryptographically valid
        proof — from the provider, never fabricated — that this exact
        (provider_order_id, provider_payment_id) pair was actually paid."""

    @abstractmethod
    def fetch_payment(self, provider_payment_id: str) -> ProviderPayment:
        """An independent, provider-authoritative check of a payment's
        current status — for reconciliation, not just trusting whatever a
        client last reported."""

    @abstractmethod
    def fetch_order(self, provider_order_id: str) -> ProviderOrder:
        """Payment Amount Validation (Phase 15) — the order side of the
        same independent-confirmation principle fetch_payment already
        gives the payment side. The order's amount/currency were only
        ever checked once, at create_order() time; re-confirming them
        fresh at verification time closes the gap where a payment's own
        reported amount could match while the order it was actually
        opened against had drifted or was never what this Payment row
        assumes."""

    @abstractmethod
    def initiate_refund(
        self, *, provider_payment_id: str, amount: Decimal, notes: dict[str, str] | None = None
    ) -> ProviderRefund:
        """Ask the provider to actually move money back. amount is always
        derived server-side by the caller (RefundService), never taken
        from a request body here or upstream."""

    @abstractmethod
    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        """True only if `signature` proves `payload` genuinely came from
        the provider's own webhook sender, unmodified."""
