"""Push Notification Service (Phase 17) — the PushProvider abstraction.

Covers ExpoPushProvider directly: send/send_batch build the right request
and translate Expo's own response shape into this package's provider-
agnostic PushSendResult vocabulary, validate_response handles a malformed
response without raising, and handle_failure recognizes exactly Expo's
"DeviceNotRegistered" as a permanent failure and nothing else. Also
covers the optional EXPO_ACCESS_TOKEN credential (kept in an environment
variable, read fresh per call, never required).
"""

import httpx
import pytest

from app.services.push.expo_provider import ExpoPushProvider
from app.services.push.provider import PushMessage, PushSendResult


class FakeResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return {"data": self._data}


def test_send_batch_posts_one_request_for_every_message(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse([{"status": "ok"}, {"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider()
    messages = [
        PushMessage(to="ExponentPushToken[a]", title="Title A", body="Body A", data={"order_id": "1"}),
        PushMessage(to="ExponentPushToken[b]", title="Title B", body="Body B"),
    ]
    results = provider.send_batch(messages)

    assert captured["url"] == "https://exp.host/--/api/v2/push/send"
    assert captured["json"] == [
        {"to": "ExponentPushToken[a]", "title": "Title A", "body": "Body A", "data": {"order_id": "1"}, "sound": "default"},
        {"to": "ExponentPushToken[b]", "title": "Title B", "body": "Body B", "data": {}, "sound": "default"},
    ]
    assert "Authorization" not in captured["headers"]  # no EXPO_ACCESS_TOKEN configured
    assert results == [
        PushSendResult(to="ExponentPushToken[a]", status="ok"),
        PushSendResult(to="ExponentPushToken[b]", status="ok"),
    ]


def test_send_batch_of_zero_messages_never_calls_the_provider(monkeypatch):
    called = False

    def fake_post(*args, **kwargs):
        nonlocal called
        called = True
        return FakeResponse([])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    assert ExpoPushProvider().send_batch([]) == []
    assert called is False


def test_send_is_a_batch_of_one(monkeypatch):
    def fake_post(url, json, timeout, headers):
        assert len(json) == 1
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    result = ExpoPushProvider().send(PushMessage(to="ExponentPushToken[a]", title="T", body="B"))
    assert result == PushSendResult(to="ExponentPushToken[a]", status="ok")


def test_access_token_is_attached_when_configured(monkeypatch):
    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["headers"] = headers
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider(access_token="test-expo-token")
    provider.send(PushMessage(to="ExponentPushToken[a]", title="T", body="B"))

    assert captured["headers"]["Authorization"] == "Bearer test-expo-token"


def test_access_token_read_from_settings_when_not_overridden(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "EXPO_ACCESS_TOKEN", "from-settings")
    captured = {}

    def fake_post(url, json, timeout, headers):
        captured["headers"] = headers
        return FakeResponse([{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    ExpoPushProvider().send(PushMessage(to="ExponentPushToken[a]", title="T", body="B"))

    assert captured["headers"]["Authorization"] == "Bearer from-settings"


def test_request_level_failure_is_reported_as_unknown_not_error(monkeypatch):
    """A network error/timeout is genuinely unresolved, not proof the
    token is bad — handle_failure must never delete a token over this.
    Retry/Failure Handling (Phase 31) — exercises the full retry budget
    (every attempt fails identically here), with backoff disabled so the
    test stays instant."""
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("network is down")

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider(backoff_seconds=0)
    results = provider.send_batch([PushMessage(to="ExponentPushToken[a]", title="T", body="B")])
    assert call_count == 3  # the full default retry budget was actually used

    assert results == [PushSendResult(to="ExponentPushToken[a]", status="unknown")]
    assert provider.handle_failure(results[0]) is False


def test_validate_response_handles_a_response_shorter_than_the_request(monkeypatch):
    provider = ExpoPushProvider()
    messages = [
        PushMessage(to="ExponentPushToken[a]", title="T", body="B"),
        PushMessage(to="ExponentPushToken[b]", title="T", body="B"),
    ]
    results = provider.validate_response(FakeResponse([{"status": "ok"}]), messages)

    assert results == [
        PushSendResult(to="ExponentPushToken[a]", status="ok"),
        PushSendResult(to="ExponentPushToken[b]", status="unknown"),
    ]


def test_validate_response_handles_malformed_json_without_raising():
    class BrokenResponse:
        def json(self):
            raise ValueError("not json")

    provider = ExpoPushProvider()
    messages = [PushMessage(to="ExponentPushToken[a]", title="T", body="B")]
    results = provider.validate_response(BrokenResponse(), messages)

    assert results == [PushSendResult(to="ExponentPushToken[a]", status="unknown")]


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (PushSendResult(to="x", status="ok"), False),
        (PushSendResult(to="x", status="unknown"), False),
        (PushSendResult(to="x", status="error", error_code="MessageTooBig"), False),
        (PushSendResult(to="x", status="error", error_code="DeviceNotRegistered"), True),
    ],
)
def test_handle_failure_recognizes_only_device_not_registered(result, expected):
    assert ExpoPushProvider().handle_failure(result) is expected


# ---------------------------------------------------------------------------
# Retry/Failure Handling (Phase 31)
# ---------------------------------------------------------------------------


class FakeResponseWithStatus:
    def __init__(self, status_code, data=None):
        self.status_code = status_code
        self._data = data or []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self):
        return {"data": self._data}


def test_a_transient_failure_that_recovers_on_a_later_attempt_succeeds(monkeypatch):
    """Provider timeout / temporary network failure — the exact case this
    phase names — recovers without ever surfacing as a permanent
    failure, as long as it resolves within the retry budget."""
    attempts = []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            raise httpx.TimeoutException("provider timeout")
        return FakeResponseWithStatus(200, [{"status": "ok"}])

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider(backoff_seconds=0)
    results = provider.send_batch([PushMessage(to="ExponentPushToken[a]", title="T", body="B")])

    assert len(attempts) == 2
    assert results == [PushSendResult(to="ExponentPushToken[a]", status="ok")]


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
def test_rate_limit_and_server_errors_are_retried(monkeypatch, status_code):
    """Rate limit (429) and temporary provider error (5xx) — both
    explicitly named by this phase — are retried, not treated as a
    permanent failure on the first response."""
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return FakeResponseWithStatus(status_code)

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider(backoff_seconds=0)
    results = provider.send_batch([PushMessage(to="ExponentPushToken[a]", title="T", body="B")])

    assert call_count == 3  # the full retry budget was used
    assert results == [PushSendResult(to="ExponentPushToken[a]", status="unknown")]


def test_a_non_retryable_4xx_fails_fast_without_burning_the_retry_budget(monkeypatch):
    """A malformed request (not a rate limit) is this backend's own bug —
    retrying the identical payload would never succeed, so this must not
    waste the retry budget repeating a guaranteed failure."""
    call_count = 0

    def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return FakeResponseWithStatus(400)

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)

    provider = ExpoPushProvider(backoff_seconds=0)
    results = provider.send_batch([PushMessage(to="ExponentPushToken[a]", title="T", body="B")])

    assert call_count == 1  # never retried
    assert results == [PushSendResult(to="ExponentPushToken[a]", status="unknown")]


def test_backoff_grows_between_attempts(monkeypatch):
    """A real (non-zero) backoff actually sleeps, and grows across
    attempts — proving this is genuine exponential backoff, not just a
    fixed short delay repeated."""
    sleep_calls = []

    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr("app.services.push.expo_provider.httpx.post", fake_post)
    monkeypatch.setattr("app.services.push.expo_provider.time.sleep", lambda seconds: sleep_calls.append(seconds))

    provider = ExpoPushProvider(max_attempts=3, backoff_seconds=0.1)
    provider.send_batch([PushMessage(to="ExponentPushToken[a]", title="T", body="B")])

    assert sleep_calls == [0.1, 0.2]  # between attempts 1->2 and 2->3; none after the last attempt
