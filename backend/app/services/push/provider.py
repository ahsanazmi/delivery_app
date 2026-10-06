"""Push Notification Service (Phase 17) — the PushProvider interface every
concrete push gateway (ExpoPushProvider today, anything else later — e.g.
a direct FCM/APNs provider if this project ever drops Expo) implements.
The same boundary discipline app/services/payment/provider.py already
established for payments: nothing outside this package should construct
or import a concrete provider directly, and nothing above this package
(push_notifications.py, and everything that calls it) ever sees a raw
provider HTTP response — only this module's own provider-agnostic
PushMessage/PushSendResult vocabulary.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class PushMessage:
    to: str
    title: str
    body: str
    data: dict | None = None


@dataclass(frozen=True)
class PushSendResult:
    to: str
    # Deliberately a provider-agnostic status vocabulary, not Expo's own
    # ("ok"/"error") passed through verbatim — "ok" and "error" happen to
    # read the same in English, but this dataclass is what every caller
    # above this package actually depends on, and a future non-Expo
    # provider must be able to report the same three outcomes without
    # this shape having to change.
    status: str  # "ok" | "error" | "unknown"
    # Only ever set when status == "error" — the provider's own error
    # code (Expo's "DeviceNotRegistered", "MessageTooBig", ...),
    # deliberately preserved as-is rather than translated, since
    # handle_failure below is the one place that needs to recognize it.
    error_code: str | None = None


class PushProvider(ABC):
    name: str

    def send(self, message: PushMessage) -> PushSendResult:
        """Convenience wrapper — every concrete provider only has to
        implement send_batch; a single message is just a batch of one.
        Not abstract: there is exactly one correct way to do this, so
        there is nothing for a subclass to override."""
        return self.send_batch([message])[0]

    @abstractmethod
    def send_batch(self, messages: list[PushMessage]) -> list[PushSendResult]:
        """Send every message in one request where the provider's own API
        supports it (Expo's does — one HTTP call for the whole batch, not
        one per message). Returns exactly one PushSendResult per message,
        in the same order, even when the request-level call itself failed
        outright (see ExpoPushProvider's own "unknown" status for that
        case) — callers can always zip() this 1:1 against their own
        messages list without checking length first."""

    @abstractmethod
    def validate_response(self, raw_response, messages: list[PushMessage]) -> list[PushSendResult]:
        """Parse a provider's raw HTTP response into this package's own
        PushSendResult vocabulary. Kept as its own method (not folded
        into send_batch) so a caller that already has a raw response
        in hand — e.g. a test fixture, or a future webhook/receipt
        endpoint — can validate it without re-sending anything."""

    @abstractmethod
    def handle_failure(self, result: PushSendResult) -> bool:
        """True only when this failure means the token itself is
        permanently invalid and safe to delete (Expo's
        "DeviceNotRegistered") — never true for a transient/ambiguous
        failure, where the token must be kept and retried later.
        push_notifications.py is the only thing that acts on this
        return value (deleting a PushToken row); this package never
        touches that table itself."""
