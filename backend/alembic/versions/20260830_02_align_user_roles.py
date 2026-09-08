"""align user roles and user profile fields

Revision ID: 20260830_02
Revises: 20260830_01
Create Date: 2026-08-30
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260830_02"
down_revision: Union[str, Sequence[str], None] = "20260830_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'MERCHANT_MANAGER' TO 'RESTAURANT'")
    op.execute("ALTER TYPE user_role RENAME VALUE 'DELIVERY_PARTNER' TO 'RIDER'")
    op.alter_column("users", "full_name", new_column_name="name")
    op.alter_column("users", "hashed_password", new_column_name="password_hash")
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=True)
    op.add_column("users", sa.Column("profile_image", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "profile_image")
    op.alter_column("users", "email", existing_type=sa.String(length=320), nullable=False)
    op.alter_column("users", "password_hash", new_column_name="hashed_password")
    op.alter_column("users", "name", new_column_name="full_name")
    op.execute("ALTER TYPE user_role RENAME VALUE 'RIDER' TO 'DELIVERY_PARTNER'")
    op.execute("ALTER TYPE user_role RENAME VALUE 'RESTAURANT' TO 'MERCHANT_MANAGER'")
