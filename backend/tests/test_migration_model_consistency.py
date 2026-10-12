"""E2E Validation Phase 3 — the test suite builds its schema with
Base.metadata.create_all() on SQLite, never by running migrations, so a
constraint declared on a model but never migrated still passes every test
while PostgreSQL silently doesn't enforce it (exactly what happened to the
two coupon CHECK constraints). This static check needs no database: every
named CHECK constraint on the models must be created by some migration."""

from pathlib import Path

from sqlalchemy import CheckConstraint

from app import models  # noqa: F401 - register every model on Base.metadata
from app.db.base import Base

VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"


def test_every_model_check_constraint_is_created_by_a_migration():
    migration_source = "\n".join(path.read_text() for path in VERSIONS_DIR.glob("*.py"))
    missing = sorted(
        f"{table.name}.{constraint.name}"
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and isinstance(constraint.name, str)
        and constraint.name not in migration_source
    )
    assert not missing, f"CHECK constraints declared on models but never migrated: {missing}"
