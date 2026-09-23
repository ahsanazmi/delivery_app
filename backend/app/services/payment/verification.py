"""Payment System Phase 4 — the generic HMAC-SHA256 signature primitive
every provider's own verify_payment_signature()/verify_webhook_signature()
is built on. Provider-agnostic on purpose (Razorpay's own signature scheme
happens to be HMAC-SHA256 over "order_id|payment_id", but this function
doesn't know or care whose scheme it's checking) — a future provider with
the same HMAC-SHA256 shape reuses this directly instead of reimplementing
constant-time comparison itself, which is exactly the kind of
provider-specific-code-scattering this phase is meant to prevent.
"""

import hashlib
import hmac


def verify_hmac_signature(payload: str, signature: str | None, secret: str) -> bool:
    """Constant-time comparison (hmac.compare_digest) — a naive `==` here
    would leak timing information an attacker could use to guess the
    correct signature one byte at a time."""
    if not signature or not secret:
        return False
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
