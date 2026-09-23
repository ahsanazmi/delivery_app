import logging

from app.core.config import settings


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
