import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AdminAuditLog(Base):
    """An append-only record of every explicit administrative intervention
    performed on another resource — never edited or deleted after creation,
    the same discipline as RiderEarning/RiderSettlement. Deliberately
    generic (target_type/target_id as free text rather than a dozen
    nullable per-resource FK columns) so the same table can record an
    intervention on any resource a future admin action might touch, not
    just orders. Written in the same DB transaction as the intervention
    itself (see admin_cancel_order/admin_reassign_rider in orders.py) so a
    mutation can never commit without its audit entry, or vice versa."""

    __tablename__ = "admin_audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    admin_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # e.g. "order.cancel", "order.reassign_rider" — a stable, greppable
    # identifier for what happened, not a human sentence.
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    previous_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_state: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Admin Portal Phase 21 — the request's source IP. Nullable since
    # entries written before this phase (Phase 11/14) have none.
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
