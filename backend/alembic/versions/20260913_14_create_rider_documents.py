"""create rider_documents table

Revision ID: 20260913_14
Revises: 20260913_13
Create Date: 2026-09-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260913_14"
down_revision: Union[str, Sequence[str], None] = "20260913_13"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    document_type = postgresql.ENUM(
        "DRIVING_LICENSE", "VEHICLE_REGISTRATION", "IDENTITY_DOCUMENT", "BANK_DOCUMENT", "PROFILE_PHOTO",
        name="rider_document_type",
        create_type=False,
    )
    document_type.create(op.get_bind(), checkfirst=True)

    verification_status = postgresql.ENUM(
        "PENDING", "APPROVED", "REJECTED",
        name="rider_document_verification_status",
        create_type=False,
    )
    verification_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rider_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", document_type, nullable=False),
        sa.Column("document_number", sa.String(length=120), nullable=True),
        sa.Column("document_url", sa.String(length=2048), nullable=False),
        sa.Column("verification_status", verification_status, nullable=False, server_default="PENDING"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("rider_id", "document_type", name="uq_rider_documents_rider_id_document_type"),
    )
    op.create_index(op.f("ix_rider_documents_rider_id"), "rider_documents", ["rider_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_rider_documents_rider_id"), table_name="rider_documents")
    op.drop_table("rider_documents")
    postgresql.ENUM(name="rider_document_verification_status").drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name="rider_document_type").drop(op.get_bind(), checkfirst=True)
