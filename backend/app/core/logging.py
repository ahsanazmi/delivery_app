import logging
import re

from app.core.config import settings

# E2E Validation Phase 21 — the customer tracking WebSocket authenticates with
# `?token=<access JWT>` (React Native's WebSocket can't send headers), and
# uvicorn logs every handshake URL — so live access tokens were being written
# to the access log (reproduced: the full JWT appeared in the server log).
_TOKEN_IN_URL = re.compile(r"((?:^|[?&])(?:access_)?token=)[^&\s\"']+", re.IGNORECASE)


def redact_tokens(value: object) -> object:
    if isinstance(value, str) and "token=" in value.lower():
        return _TOKEN_IN_URL.sub(r"\1[REDACTED]", value)
    return value


class RedactTokenQueryParamFilter(logging.Filter):
    """Rewrites `token=…` query parameters in a record's message and args.
    Attached to uvicorn's own loggers, which log request URLs verbatim."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_tokens(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact_tokens(arg) for arg in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact_tokens(arg) for key, arg in record.args.items()}
        return True


def setup_logging() -> None:
    """Logging & Error Handling (Phase 26) — the app previously had no
    logging configuration at all (no handlers, no format, nothing beyond
    Uvicorn's own access log). Call once at startup. Every module below
    gets its own logger via `logging.getLogger(__name__)`, the standard
    library idiom — no custom wrapper needed, since stdlib logging already
    gives every one of those loggers this same root configuration.

    Never call this with anything that could contain a password, JWT
    access/refresh token, or payment secret in `msg`/`args` — see each call
    site's own comment for what it deliberately logs instead (user id,
    order id, path — identifiers, never credentials)."""
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL.upper(), logging.WARNING),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # uvicorn.access logs HTTP request lines; uvicorn.error logs the
    # WebSocket handshake line ('"WebSocket /path?token=…" [accepted]').
    token_filter = RedactTokenQueryParamFilter()
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(token_filter)
