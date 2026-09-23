"""create cod_collections and cod_settlement_allocations tables

Revision ID: 20261003_44
Revises: 20261002_43
Create Date: 2026-10-03
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261003_44"
down_revision: Union[str, Sequence[str], None] = "20261002_43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cod_collections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id", name="uq_cod_collections_payment_id"),
    )
    op.create_index(op.f("ix_cod_collections_payment_id"), "cod_collections", ["payment_id"], unique=False)
    op.create_index(op.f("ix_cod_collections_order_id"), "cod_collections", ["order_id"], unique=False)
    op.create_index(op.f("ix_cod_collections_rider_id"), "cod_collections", ["rider_id"], unique=False)

    op.create_table(
        "cod_settlement_allocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("settlement_id", sa.Uuid(), nullable=False),
        sa.Column("cod_collection_id", sa.Uuid(), nullable=False),
        sa.Column("amount_allocated", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["settlement_id"], ["rider_settlements.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cod_collection_id"], ["cod_collections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_allocated > 0", name="ck_cod_settlement_allocations_amount_positive"),
    )
    op.create_index(
        op.f("ix_cod_settlement_allocations_settlement_id"), "cod_settlement_allocations", ["settlement_id"], unique=False
    )
    op.create_index(
        op.f("ix_cod_settlement_allocations_cod_collection_id"),
        "cod_settlement_allocations", ["cod_collection_id"], unique=False,
    )

    # Backfill: every COD payment already collected before this table
    # existed needs its own ledger row too, or admin_settle_cod()'s FIFO
    # allocation invariant (every settlement fully allocates against this
    # rider's own unallocated collections, because their sum always
    # equals the rider's outstanding balance) would be violated for any
    # rider with pre-existing collections — their outstanding balance
    # would count cash no CodCollection row backs.
    op.execute(
        """
        INSERT INTO cod_collections (id, payment_id, order_id, rider_id, amount, collected_at, created_at)
        SELECT gen_random_uuid(), id, order_id, collected_by_rider_id, amount, collected_at, now()
        FROM payments
        WHERE provider = 'cod' AND collected_by_rider_id IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_cod_settlement_allocations_cod_collection_id"), table_name="cod_settlement_allocations")
    op.drop_index(op.f("ix_cod_settlement_allocations_settlement_id"), table_name="cod_settlement_allocations")
    op.drop_table("cod_settlement_allocations")

    op.drop_index(op.f("ix_cod_collections_rider_id"), table_name="cod_collections")
    op.drop_index(op.f("ix_cod_collections_order_id"), table_name="cod_collections")
    op.drop_index(op.f("ix_cod_collections_payment_id"), table_name="cod_collections")
    op.drop_table("cod_collections")
