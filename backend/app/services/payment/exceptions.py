"""Payment System Phase 4 — a typed error vocabulary for the payment
service layer. Deliberately plain Python exceptions, not HTTPException:
this package has no dependency on FastAPI at all, so a route handler
(when one is wired to call it, in a later phase) translates these to the
right status code itself, and any future non-HTTP caller (a background
job, a CLI script) never has to import a web-framework exception just to
catch a payment failure.
"""


class PaymentError(Exception):
    """Base class for every exception this package raises."""


class ProviderNotConfiguredError(PaymentError):
    """Raised when a provider is asked to do something that requires
    credentials (RAZORPAY_KEY_ID/SECRET, the webhook secret) that aren't
    set. Mirrors the existing app/services/payments.py principle: never
    fabricate success when there's no way to have actually verified
    anything — refuse honestly instead."""


class ProviderRequestError(PaymentError):
    """Raised when a call to the provider's own API fails — a network
    error, a timeout, or the provider itself returning an error response."""


class PaymentVerificationError(PaymentError):
    """Raised when a payment's signature/authenticity could not be
    verified — the provider was reachable and configured, but what it (or
    the client) sent back doesn't check out."""


class PaymentExpiredError(PaymentError):
    """Raised when a customer tries to verify or retry a payment whose
    checkout window (Payment Failure & Recovery Testing, Phase 32) has
    already closed — distinct from a genuine PaymentVerificationError: an
    abandoned checkout isn't a rejection or an attack, it's a normal,
    routine outcome that simply needs its own clean, terminal, no-longer-
    actionable state rather than staying ambiguously retryable forever."""


class RefundError(PaymentError):
    """Raised when a refund cannot proceed — the payment isn't in a
    refundable state, or the requested amount exceeds what's left to
    refund."""
