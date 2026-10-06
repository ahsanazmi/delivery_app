import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PushToken(Base):
    """Notifications & Communication System Phase 14 — Push Token Domain.

    One row per *device*, not per user — a user with the app installed on
    two phones has two rows here, and both are sent to (see
    push_notifications.py's send_push_to_user/send_push_to_users, which
    already query by user_id and loop over every matching row). Never
    assume a user has at most one token.

    device_identifier is the stable per-device key a client can supply
    (an Expo-installation id, or any locally-generated id the client
    persists) so a later re-registration from the *same* device — most
    commonly because its push token itself rotated, which both iOS and
    Android push services do periodically, not just on reinstall — updates
    this same row's token in place (see upsert_push_token) instead of
    leaving the old, now-dead token behind as an orphaned row that would
    otherwise linger until Expo happens to bounce a push off it. It is
    nullable and optional: a client that doesn't send one falls back to
    the original (user_id, token) matching this table has always used.
    """

    __tablename__ = "push_tokens"
    __table_args__ = (UniqueConstraint("user_id", "token", name="uq_push_tokens_user_token"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    platform: Mapped[str] = mapped_column(String(32), default="expo", nullable=False)
    device_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
