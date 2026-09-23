import logging
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.db.session import get_db
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """The single choke point every authenticated request passes through —
    also the single place a rejected/forged/expired token is logged
    (Logging & Error Handling, Phase 26). Never logs the token itself
    (credentials.credentials) — only that this path saw a bad one, and why,
    which is enough to spot a brute-force/enumeration pattern without ever
    putting a live bearer token in a log file."""
    credentials_error = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")
    if not credentials:
        logger.warning("Authentication failed on %s: no bearer token provided", request.url.path)
        raise credentials_error
    try:
        user_id: UUID = decode_token(credentials.credentials, "access")
    except (jwt.PyJWTError, ValueError) as exc:
        logger.warning("Authentication failed on %s: invalid or expired token (%s)", request.url.path, type(exc).__name__)
        raise credentials_error from None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        logger.warning("Authentication failed on %s: token valid but user %s not found or inactive", request.url.path, user_id)
        raise credentials_error
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    def verify_role(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            # Logging & Error Handling (Phase 26) — every role-based 403 in
            # the app passes through this one function (require_customer/
            # _rider/_admin all call it directly, not just via Depends(), so
            # it can't take a FastAPI-injected Request param without
            # breaking those direct calls) — this is the single place an
            # authorization failure is logged, regardless of which endpoint
            # or role gate rejected it.
            logger.warning(
                "Authorization failed: user %s (role=%s) lacks one of %s",
                current_user.id, current_user.role.value, [r.value for r in roles],
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return current_user

    return verify_role


def require_customer(current_user: CurrentUser) -> User:
    """Integration Phase 2 — every /api/v1/customer/* route previously used
    the bare CurrentUser dependency (any authenticated role, scoped only by
    matching current_user.id against a resource's owner column). That never
    caused a cross-role *data* leak, since a rider/owner/admin has no
    customer-role rows under their own id, but it did mean any authenticated
    account — regardless of role — could call these endpoints at all (e.g.
    place an order, add a favorite) and get a 200, not the 403 role
    isolation demands. Same ready-made-dependency pattern as require_rider/
    require_admin, for the same OpenAPI-visibility reason."""
    return require_roles(UserRole.CUSTOMER)(current_user)


def require_rider(current_user: CurrentUser) -> User:
    """A ready-made dependency (unlike require_roles, which is a factory) so
    every rider-facing endpoint can just write Depends(require_rider) — one
    canonical gate for "all Rider APIs must use rider authorization"."""
    return require_roles(UserRole.RIDER)(current_user)


def require_admin(current_user: CurrentUser) -> User:
    """Admin Portal Phase 1 — the same ready-made-dependency pattern as
    require_rider, declared via Depends(require_admin) in each admin
    endpoint's own signature so FastAPI's dependency graph (and therefore
    its generated OpenAPI schema) correctly reflects the auth requirement,
    rather than an inline check buried in the function body that Depends()
    can't see."""
    return require_roles(UserRole.ADMIN)(current_user)
