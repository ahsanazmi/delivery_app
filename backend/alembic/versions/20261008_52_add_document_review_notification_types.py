"""add document_approved and document_rejected notification types

Revision ID: 20261008_52
Revises: 20261007_51
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261008_52"
down_revision: Union[str, Sequence[str], None] = "20261007_51"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_VALUES = (
    "document_approved",
    "document_rejected",
)


def upgrade() -> None:
    for value in _NEW_VALUES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop individual enum values; the added labels are
    # left in place on downgrade — same precedent as every other
    # enum-value-addition migration in this project.
    pass
