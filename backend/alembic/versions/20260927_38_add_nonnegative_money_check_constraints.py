"""add non-negative check constraints on order/payment/rider_settlement amounts

Revision ID: 20260927_38
Revises: 20260926_37
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260927_38"
down_revision: Union[str, Sequence[str], None] = "20260926_37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_orders_subtotal_nonnegative", "orders", "subtotal >= 0")
    op.create_check_constraint("ck_orders_delivery_fee_nonnegative", "orders", "delivery_fee >= 0")
    op.create_check_constraint("ck_orders_tax_nonnegative", "orders", "tax >= 0")
    op.create_check_constraint("ck_orders_discount_nonnegative", "orders", "discount >= 0")
    op.create_check_constraint("ck_orders_total_nonnegative", "orders", "total >= 0")
    op.create_check_constraint("ck_payments_amount_nonnegative", "payments", "amount >= 0")
    op.create_check_constraint("ck_rider_settlements_amount_nonnegative", "rider_settlements", "amount >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_orders_subtotal_nonnegative", "orders", type_="check")
    op.drop_constraint("ck_orders_delivery_fee_nonnegative", "orders", type_="check")
    op.drop_constraint("ck_orders_tax_nonnegative", "orders", type_="check")
    op.drop_constraint("ck_orders_discount_nonnegative", "orders", type_="check")
    op.drop_constraint("ck_orders_total_nonnegative", "orders", type_="check")
    op.drop_constraint("ck_payments_amount_nonnegative", "payments", type_="check")
    op.drop_constraint("ck_rider_settlements_amount_nonnegative", "rider_settlements", type_="check")
