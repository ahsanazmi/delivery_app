import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CommissionType(str, enum.Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED = "FIXED"


class CommissionRule(Base):
    """Admin Portal Phase 17 — a platform commission rule. restaurant_id
    NULL means the platform-wide default; a non-null restaurant_id is a
    restaurant-specific override that takes precedence over the default for
    that one restaurant. At most one default row and at most one row per
    restaurant are ever supposed to exist — enforced in admin_commissions.py
    (always find-then-update-or-create, never a blind insert), not by a
    database constraint, since "at most one NULL" isn't expressible as a
    plain unique constraint and a Postgres-only partial index would need a
    separate SQLite equivalent for the test suite.

    Changing a rule here only ever affects orders placed *after* the
    change — see Order.commission_amount and create_order(), which compute
    and snapshot the applicable rule once, at order-creation time. Nothing
    in this codebase ever re-reads a CommissionRule to recompute a
    historical order's already-stored commission."""

    __tablename__ = "commission_rules"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    restaurant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=True, index=True
    )
    commission_type: Mapped[CommissionType] = mapped_column(
        Enum(CommissionType, name="commission_type", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    # A percentage (0-100) or a fixed currency amount, depending on
    # commission_type — never both meanings at once.
    value: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
