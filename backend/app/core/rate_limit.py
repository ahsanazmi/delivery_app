import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

# In-memory, per-process sliding-window limiter. This app runs as a single
# uvicorn worker today (see app/ws/manager.py for the same caveat) — fine for
# that, but a multi-instance deployment would need a shared store (e.g. Redis)
# behind this same function signature for the limit to hold across processes.
_attempts: dict[str, deque[float]] = defaultdict(deque)


def rate_limit(request: Request, *, max_attempts: int, window_seconds: int) -> None:
    """Raises 429 if this client has made too many requests to this path
    within the window. Keyed by path+IP so different sensitive endpoints
    (login, register) don't share one budget."""
    client_ip = request.client.host if request.client else "unknown"
    key = f"{request.url.path}:{client_ip}"
    now = time.monotonic()
    bucket = _attempts[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )
    bucket.append(now)
