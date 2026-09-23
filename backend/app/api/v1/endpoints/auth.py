import logging

import jwt
from fastapi import APIRouter, HTTPException, Request, status

from app.api.v1.deps import CurrentUser, DbSession
from app.core.rate_limit import rate_limit
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, RefreshTokenRequest, RegisterRequest, TokenPair
from app.schemas.user import UserRead
from app.services.auth import authenticate_user, get_user_by_email, get_user_by_phone, register_user

logger = logging.getLogger(__name__)

router = APIRouter()


def issue_token_pair(user_id) -> TokenPair:
    return TokenPair(access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession, request: Request) -> UserRead:
    rate_limit(request, max_attempts=5, window_seconds=60)
    # CUSTOMER and RIDER are open self-registration, matching how real
    # delivery platforms onboard riders (sign up, then get vetted/approved
    # before going online — that approval gate is a later Rider Portal
    # phase). RESTAURANT_OWNER and ADMIN stay admin-provisioned only.
    if payload.role and payload.role not in (UserRole.CUSTOMER, UserRole.RIDER):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Public registration is only allowed for CUSTOMER or RIDER roles",
        )
    if get_user_by_email(db, str(payload.email)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this email already exists")
    if payload.phone and get_user_by_phone(db, payload.phone):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An account with this phone number already exists")
    return register_user(db, payload)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DbSession, request: Request) -> TokenPair:
    rate_limit(request, max_attempts=10, window_seconds=60)
    email = (payload.email or "").strip() or None
    phone = (payload.phone or "").strip() or None
    user = authenticate_user(db, email=email, phone=phone, password=payload.password)
    if not user or not user.is_active:
        # Logging & Error Handling (Phase 26) — the identifier attempted is
        # useful for spotting brute-force/enumeration patterns; the password
        # itself (payload.password) must never appear in a log line, here or
        # anywhere else.
        logger.warning("Login failed for identifier %r", email or phone)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email, phone, or password")
    return issue_token_pair(user.id)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshTokenRequest, db: DbSession, request: Request) -> TokenPair:
    rate_limit(request, max_attempts=20, window_seconds=60)
    try:
        user_id = decode_token(payload.refresh_token, "refresh")
    except (jwt.PyJWTError, ValueError) as exc:
        # Never log payload.refresh_token itself — only that this attempt failed and why.
        logger.warning("Token refresh failed: invalid or expired refresh token (%s)", type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token") from None
    user = db.get(User, user_id)
    if not user or not user.is_active:
        logger.warning("Token refresh failed: token valid but user %s not found or inactive", user_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    return issue_token_pair(user.id)


@router.get("/me", response_model=UserRead)
def get_me(current_user: CurrentUser) -> UserRead:
    return current_user


@router.post("/logout")
def logout(current_user: CurrentUser) -> dict[str, str]:
    _ = current_user
    return {"message": "Logged out successfully"}
