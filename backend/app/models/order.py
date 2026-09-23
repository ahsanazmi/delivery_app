import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrderStatus(str, enum.Enum):
    PLACED = "placed"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY_FOR_PICKUP = "ready_for_pickup"
    RIDER_ASSIGNED = "rider_assigned"
    PICKED_UP = "picked_up"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # Financial Consistency Test (Phase 23) — every other money-bearing
        # table in this codebase (Product.price, Restaurant.minimum_order/
        # delivery_fee, Coupon.discount_value/min_order) already has a
        # non-negative CheckConstraint; Order — the single most financially
        # critical table — didn't. Application logic already guarantees
        # these stay non-negative (calculate_coupon_discount caps discount
        # at the pre-discount total, so total can never go negative), so
        # this is defense-in-depth, not a behavior change.
        CheckConstraint("subtotal >= 0", name="ck_orders_subtotal_nonnegative"),
        CheckConstraint("delivery_fee >= 0", name="ck_orders_delivery_fee_nonnegative"),
        CheckConstraint("tax >= 0", name="ck_orders_tax_nonnegative"),
        CheckConstraint("discount >= 0", name="ck_orders_discount_nonnegative"),
        CheckConstraint("total >= 0", name="ck_orders_total_nonnegative"),
        Index("ix_orders_user_id_created_at", "user_id", "created_at"),
        Index("ix_orders_user_id_status", "user_id", "status"),
        # Phase 30 — every rider-facing query filters rider_id together with
        # either a specific status or an IN-list of statuses: available-
        # deliveries' rider_id IS NULL check, the dashboard's completed/
        # pending counts and current_assignment, and history's status IN
        # (DELIVERED, CANCELLED). A single-column index on rider_id alone
        # (already present below) still has to scan/filter every one of
        # this rider's orders by status afterward; this composite lets
        # Postgres satisfy both predicates from the index directly.
        Index("ix_orders_rider_id_status", "rider_id", "status"),
        # Performance Baseline (Phase 25) — the same rationale as the two
        # composites above, for the two remaining call sites that filter
        # Order by a column other than its own primary key and then sort by
        # created_at: list_restaurant_orders (the "Restaurant orders" API —
        # restaurant_id alone, already indexed below, still needs a
        # separate sort step for every page) and the admin dashboard +
        # every admin_reports.py report (all filter by status, most of them
        # combined with a created_at range, over the whole table — the
        # single busiest, fastest-growing table in the schema, unlike
        # Restaurant/DeliveryPartner/User which stay small enough that an
        # unindexed scan is still cheap).
        Index("ix_orders_restaurant_id_created_at", "restaurant_id", "created_at"),
        Index("ix_orders_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # Snapshots below are captured at order-creation time and never re-derived from
    # live customer/restaurant/product records — a later profile edit, menu change,
    # or account deletion must not alter historical orders.
    customer_name: Mapped[str] = mapped_column(String(120), nullable=False)
    customer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    restaurant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    restaurant_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    restaurant_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    restaurant_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    order_number: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        default=OrderStatus.PLACED,
        nullable=False,
    )
    payment_method: Mapped[str] = mapped_column(String(32), default="cod", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    delivery_fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    tax: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    discount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    total: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    address_line: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    postal_code: Mapped[str] = mapped_column(String(20), nullable=False)
    landmark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    delivery_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Admin Portal Phase 17 — the commission rule in effect is computed and
    # snapshotted once, at order-creation time (see create_order in
    # orders.py), exactly like subtotal/delivery_fee/tax/discount above.
    # All three stay NULL for an order placed before this feature existed,
    # or if no commission rule applied to it at all — never backfilled with
    # a guessed value, and never recomputed later even if the rule changes.
    commission_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    commission_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    status_history: Mapped[list["OrderStatusHistory"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    payments: Mapped[list["Payment"]] = relationship("Payment", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    restaurant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order: Mapped[Order] = relationship(back_populates="items")


class OrderStatusHistory(Base):
    __tablename__ = "order_status_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status_history_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    order: Mapped[Order] = relationship(back_populates="status_history")
