"""add constraints declared on models but never migrated

Revision ID: 20261012_58
Revises: 20261011_57
Create Date: 2026-10-12

E2E Validation Phase 3 — a schema comparison of a freshly migrated
database against Base.metadata found two coupon CHECK constraints
(Financial Consistency Test Phase 23) that exist on the Coupon model but
were never created by any migration, so PostgreSQL never enforced them —
only the API schemas did. Also restores push_tokens.last_seen_at's
server default: the model declares server_default=now(), but migration
20261009_53 added the column as NOT NULL without one.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261012_58"
down_revision: Union[str, Sequence[str], None] = "20261011_57"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("coupons") as batch_op:
        batch_op.create_check_constraint("ck_coupons_discount_value_nonnegative", "discount_value >= 0")
        batch_op.create_check_constraint("ck_coupons_min_order_nonnegative", "min_order >= 0")

    with op.batch_alter_table("push_tokens") as batch_op:
        batch_op.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), server_default=sa.func.now())


def downgrade() -> None:
    with op.batch_alter_table("push_tokens") as batch_op:
        batch_op.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), server_default=None)

    with op.batch_alter_table("coupons") as batch_op:
        batch_op.drop_constraint("ck_coupons_min_order_nonnegative", type_="check")
        batch_op.drop_constraint("ck_coupons_discount_value_nonnegative", type_="check")
