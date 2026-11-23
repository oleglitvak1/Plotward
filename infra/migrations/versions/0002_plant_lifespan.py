"""plant lifespan

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-23 03:17:22.565737
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
import pgvector.sqlalchemy


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("plant", sa.Column("kind", sa.String(length=16), nullable=True))
    op.add_column("plant", sa.Column("ended_on", sa.Date(), nullable=True))
    # Existing rows must satisfy the new constraint: removed plants get an end date.
    op.execute("UPDATE plant SET ended_on = current_date WHERE status = 'removed'")
    op.create_check_constraint(
        "plant_kind_valid", "plant", "kind is null or kind in ('perennial', 'annual')"
    )
    op.create_check_constraint(
        "plant_end_matches_status", "plant", "(status = 'removed') = (ended_on is not null)"
    )


def downgrade() -> None:
    op.drop_constraint("plant_end_matches_status", "plant", type_="check")
    op.drop_constraint("plant_kind_valid", "plant", type_="check")
    op.drop_column("plant", "ended_on")
    op.drop_column("plant", "kind")
