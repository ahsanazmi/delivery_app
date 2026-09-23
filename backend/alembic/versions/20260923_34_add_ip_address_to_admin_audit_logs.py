"""add ip_address to admin_audit_logs

Revision ID: 20260923_34
Revises: 20260922_33
Create Date: 2026-09-23
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_34"
down_revision: Union[str, Sequence[str], None] = "20260922_33"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Admin Portal Phase 21 — the request's source IP, alongside the
    # existing admin_id/reason, for the audit trail. Nullable: pre-existing
    # rows (Phase 11/14) have none, and it's still useful to know who and
    # why even when the network layer can't tell us where from.
    op.add_column("admin_audit_logs", sa.Column("ip_address", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("admin_audit_logs", "ip_address")
