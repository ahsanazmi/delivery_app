"""rename RESTAURANT role to RESTAURANT_OWNER

Revision ID: 20260910_08
Revises: 20260910_07
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260910_08"
down_revision: Union[str, Sequence[str], None] = "20260910_07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'RESTAURANT' TO 'RESTAURANT_OWNER'")


def downgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'RESTAURANT_OWNER' TO 'RESTAURANT'")
