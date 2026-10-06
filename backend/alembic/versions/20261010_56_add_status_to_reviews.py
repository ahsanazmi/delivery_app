"""add status to reviews

Revision ID: 20261010_56
Revises: 20261009_55
Create Date: 2026-10-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261010_56"
down_revision: Union[str, Sequence[str], None] = "20261009_55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    review_status = postgresql.ENUM(
        "published", "hidden", "flagged", "removed",
        name="review_status",
        create_type=False,
    )
    review_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "reviews",
        sa.Column("status", review_status, nullable=False, server_default="published"),
    )


def downgrade() -> None:
    op.drop_column("reviews", "status")
    postgresql.ENUM(name="review_status").drop(op.get_bind(), checkfirst=True)
