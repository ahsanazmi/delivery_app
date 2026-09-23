from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.schemas.auth import RegisterRequest
from app.services.notifications import notify_admins


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == email.lower()))


def get_user_by_phone(db: Session, phone: str) -> User | None:
    return db.scalar(select(User).where(User.phone == phone.strip()))


def get_user_by_email_or_phone(db: Session, *, email: str | None = None, phone: str | None = None) -> User | None:
    if email:
        user = get_user_by_email(db, email)
        if user:
            return user
    if phone:
        return get_user_by_phone(db, phone)
    return None


def register_user(db: Session, payload: RegisterRequest) -> User:
    user = User(
        name=payload.name.strip(),
        email=str(payload.email).lower(),
        phone=payload.phone.strip() if payload.phone else None,
        password_hash=hash_password(payload.password),
        role=payload.role or UserRole.CUSTOMER,
    )
    db.add(user)
    db.flush()
    if user.role == UserRole.RIDER:
        # Admin Portal Phase 20 — only riders, not every new signup; a new
        # customer isn't an operational alert an admin needs to act on.
        notify_admins(
            db, NotificationType.NEW_RIDER_REGISTERED, "New rider registered",
            f"{user.name} has registered as a rider and is awaiting approval.",
        )
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, *, email: str | None = None, phone: str | None = None, password: str = "") -> User | None:
    user = get_user_by_email_or_phone(db, email=email, phone=phone)
    if not user or not verify_password(password, user.password_hash):
        return None
    return user
