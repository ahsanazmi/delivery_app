"""expand order status enum and add order snapshot fields

Revision ID: 20260910_01
Revises: 20260909_05
Create Date: 2026-09-10

Adds the full order lifecycle (READY_FOR_PICKUP, RIDER_ASSIGNED, PICKED_UP,
REJECTED) and renames PENDING -> PLACED to match the customer-facing wording.
Also adds tax/discount and customer/restaurant-address snapshot columns so an
order fully reflects everything at the moment it was placed, independent of
later changes to the customer's profile or the restaurant's data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_01"
down_revision: Union[str, Sequence[str], None] = "20260909_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NEW_VALUES = ["ready_for_pickup", "rider_assigned", "picked_up", "rejected"]


def upgrade() -> None:
    for enum_name in ("order_status", "order_status_history_status"):
        for value in NEW_VALUES:
            op.execute(f"ALTER TYPE {enum_name} ADD VALUE IF NOT EXISTS '{value}'")
        op.execute(f"ALTER TYPE {enum_name} RENAME VALUE 'pending' TO 'placed'")

    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'placed'")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("customer_name", sa.String(length=120), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("customer_email", sa.String(length=255), nullable=False, server_default=""))
        batch_op.add_column(sa.Column("customer_phone", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("restaurant_address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("tax", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"))
        batch_op.add_column(sa.Column("discount", sa.Numeric(precision=10, scale=2), nullable=False, server_default="0.00"))

    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column("customer_name", server_default=None)
        batch_op.alter_column("customer_email", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_column("discount")
        batch_op.drop_column("tax")
        batch_op.drop_column("restaurant_address")
        batch_op.drop_column("customer_phone")
        batch_op.drop_column("customer_email")
        batch_op.drop_column("customer_name")

    for enum_name in ("order_status", "order_status_history_status"):
        op.execute(f"ALTER TYPE {enum_name} RENAME VALUE 'placed' TO 'pending'")
    op.execute("ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending'")
    # Postgres cannot drop individual enum values; the added labels are left in
    # place on downgrade (harmless — nothing references them once the app code
    # that used them is reverted).
