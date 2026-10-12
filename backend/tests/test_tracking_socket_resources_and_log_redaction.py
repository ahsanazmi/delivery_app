"""E2E Validation Phase 21 — reproduced live on PostgreSQL:
(A2) every open customer tracking WebSocket held a pooled DB connection
"idle in transaction" for its whole life, so 15 sockets (pool 5 + 10
overflow) made every other request wait 30 s and fail with a 500;
(A16) the socket's `?token=<access JWT>` was written to the server log."""

import logging

from app.api.v1.customer import tracking as tracking_module
from app.core.logging import RedactTokenQueryParamFilter


class _FakeSession:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_the_initial_snapshot_releases_the_db_session(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(tracking_module, "build_tracking_snapshot", lambda db, order: object())

    class _Response:
        def model_dump(self, mode):
            return {"order_status": "rider_assigned"}

    monkeypatch.setattr(tracking_module, "to_tracking_response", lambda snapshot: _Response())

    payload = tracking_module._initial_payload_then_release_db(session, order=None)

    assert payload == {"order_status": "rider_assigned"}
    assert session.closed is True


def test_the_db_session_is_released_even_if_the_snapshot_fails(monkeypatch):
    session = _FakeSession()

    def boom(db, order):
        raise RuntimeError("routing provider down")

    monkeypatch.setattr(tracking_module, "build_tracking_snapshot", boom)
    try:
        tracking_module._initial_payload_then_release_db(session, order=None)
    except RuntimeError:
        pass
    assert session.closed is True


def test_websocket_handshake_log_lines_never_contain_the_token():
    record = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 0, '%s - "WebSocket %s" [accepted]',
        ("127.0.0.1:5000", "/api/v1/customer/ws/orders/abc?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2ln"), None,
    )
    RedactTokenQueryParamFilter().filter(record)
    message = record.getMessage()
    assert "eyJ" not in message
    assert "token=[REDACTED]" in message


def test_uvicorn_loggers_carry_the_redaction_filter():
    from app.core.logging import setup_logging

    setup_logging()
    for name in ("uvicorn.access", "uvicorn.error"):
        assert any(isinstance(f, RedactTokenQueryParamFilter) for f in logging.getLogger(name).filters)
