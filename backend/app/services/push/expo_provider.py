"""Push Notification Service (Phase 17) — the only file in this codebase
that knows Expo's specific push REST API shape (endpoint, request/response
JSON, its own "DeviceNotRegistered" vocabulary). Everything else —
push_notifications.py, and everything that calls it — only ever sees the
provider-agnostic PushProvider interface and its PushMessage/
PushSendResult dataclasses, the same boundary
app/services/payment/razorpay_provider.py already keeps for Razorpay.

Uses httpx directly against Expo's documented push API
(https://docs.expo.dev/push-notifications/sending-notifications/) rather
than adding expo-server-sdk as a new dependency — httpx is already a
dependency of this project, and Expo's push API is a single small
endpoint.
"""

import logging
import time

import httpx

from app.core.config import settings
from app.core.observability import log_event
from app.services.push.provider import PushMessage, PushProvider, PushSendResult

_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

logger = logging.getLogger(__name__)

# Retry/Failure Handling (Phase 31) — bounded and short on purpose. This
# runs synchronously on the request thread for most callers (this
# backend has no background task queue outside the one BackgroundTasks-
# deferred webhook path) — notifications are secondary to the
# transactional business logic that triggered them, so even a fully
# exhausted retry budget must add at most a fraction of a second, never
# meaningfully delay an order/payment/COD operation waiting on this call
# to return.
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.2
# Retryable server-side statuses: 429 (rate limit — Expo's own documented
# "back off and retry" signal) and 5xx (temporary provider error). Any
# other 4xx is a malformed-request bug on this backend's own side that
# retrying identically would never fix — permanent, not retried.
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ExpoPushProvider(PushProvider):
    name = "expo"

    def __init__(
        self, *, access_token: str | None = None, timeout: float = 5.0,
        max_attempts: int = _MAX_ATTEMPTS, backoff_seconds: float = _BASE_BACKOFF_SECONDS,
    ) -> None:
        # An explicit override is stored as-is; leaving it out means "read
        # settings.EXPO_ACCESS_TOKEN fresh on every call," the same
        # deferred-settings-read RazorpayProvider already established —
        # this module builds exactly one ExpoPushProvider() at import
        # time (see push_notifications.py), so caching the setting here
        # would mean a later config change silently never taking effect.
        self._access_token_override = access_token
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._backoff_seconds = backoff_seconds

    @property
    def _access_token(self) -> str | None:
        token = self._access_token_override if self._access_token_override is not None else settings.EXPO_ACCESS_TOKEN
        return token or None

    def send_batch(self, messages: list[PushMessage]) -> list[PushSendResult]:
        if not messages:
            return []

        payload = [
            {"to": m.to, "title": m.title, "body": m.body, "data": m.data or {}, "sound": "default"}
            for m in messages
        ]
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # Push Notification Service (Phase 17) — "keep provider
        # credentials in environment variables." Expo's push API accepts
        # an optional access token (https://docs.expo.dev/push-
        # notifications/sending-notifications/#additional-security)
        # purely to raise its own rate limits and tie usage to this
        # project's own Expo account; unset by default, exactly like
        # RAZORPAY_* before a merchant account is configured.
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"

        for attempt in range(self._max_attempts):
            is_last_attempt = attempt == self._max_attempts - 1
            try:
                response = httpx.post(_EXPO_PUSH_URL, json=payload, timeout=self._timeout, headers=headers)
            except httpx.RequestError:
                # Provider timeout / network failure — genuinely transient,
                # retried. Every message is unresolved (never "error") if
                # every attempt is eventually exhausted: a network blip is
                # never proof a token is dead, so handle_failure must never
                # act on it.
                if is_last_attempt:
                    logger.warning("Push delivery exhausted all %d attempts (request error)", self._max_attempts)
                    return [PushSendResult(to=m.to, status="unknown") for m in messages]
                log_event(logger, "notification_retry", attempt=attempt + 1, reason="request_error", recipient_count=len(messages))
                time.sleep(self._backoff_seconds * (2**attempt))
                continue

            if response.status_code in _RETRYABLE_STATUS_CODES:
                if is_last_attempt:
                    logger.warning(
                        "Push delivery exhausted all %d attempts (HTTP %d)", self._max_attempts, response.status_code
                    )
                    return [PushSendResult(to=m.to, status="unknown") for m in messages]
                log_event(logger, "notification_retry", attempt=attempt + 1, reason=f"http_{response.status_code}", recipient_count=len(messages))
                time.sleep(self._backoff_seconds * (2**attempt))
                continue

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError:
                # A non-retryable 4xx — a malformed request on this
                # backend's own side; retrying the identical payload would
                # never succeed, so this fails fast rather than burning
                # the rest of the retry budget on a guaranteed repeat.
                return [PushSendResult(to=m.to, status="unknown") for m in messages]

            return self.validate_response(response, messages)

        # Unreachable (the loop above always returns), but keeps type
        # checkers honest about send_batch's own declared return type.
        return [PushSendResult(to=m.to, status="unknown") for m in messages]

    def validate_response(self, raw_response: httpx.Response, messages: list[PushMessage]) -> list[PushSendResult]:
        try:
            raw_results = raw_response.json().get("data", [])
        except Exception:
            return [PushSendResult(to=m.to, status="unknown") for m in messages]

        results = []
        for message, raw in zip(messages, raw_results):
            if not isinstance(raw, dict):
                results.append(PushSendResult(to=message.to, status="unknown"))
                continue
            status = raw.get("status", "unknown")
            error_code = raw.get("details", {}).get("error") if status == "error" else None
            results.append(PushSendResult(to=message.to, status=status, error_code=error_code))
        # Expo's own response array can legitimately be shorter than the
        # request (a malformed/undersized response) — any message with no
        # corresponding entry is unresolved, not silently dropped.
        for message in messages[len(raw_results):]:
            results.append(PushSendResult(to=message.to, status="unknown"))
        return results

    def handle_failure(self, result: PushSendResult) -> bool:
        return result.status == "error" and result.error_code == "DeviceNotRegistered"
