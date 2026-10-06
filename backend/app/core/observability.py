import logging

# Live Rider Tracking Phase 39 — Observability. This codebase's existing
# logging (see e.g. services/orders.py's own warnings) is plain %-style
# message interpolation — fine for a human reading the console, but not
# reliably machine-parseable. Structured logging here means each tracking
# lifecycle event is always the same shape: a fixed `event=<name>` token
# plus a flat set of key=value fields (logfmt — parseable by a log
# aggregator with a one-line regex, no JSON parser required, and still
# readable directly in a terminal). Kept as one small, shared helper
# rather than duplicating this formatting at every call site.
#
# NEVER pass a field containing an access token, a refresh token, or any
# other secret/credential; NEVER pass unnecessary personal information
# (a customer/rider's name, email, phone, raw address text — an id is
# fine, since it's already how every other log in this codebase
# identifies a user/order); NEVER pass payment details (card/UPI
# identifiers, raw amounts tied to a specific payment method). Every
# call site below only ever logs ids, coordinates, statuses, and reasons
# — see docs/live-tracking-architecture.md's Observability section for
# the audited list.


def log_event(logger: logging.Logger, event: str, **fields: object) -> None:
    formatted = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("event=%s %s", event, formatted)
