"""photo match result

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-23 03:47:41.072521
"""
from alembic import op
import sqlalchemy as sa
import geoalchemy2
import pgvector.sqlalchemy


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("photo", sa.Column("match_method", sa.String(length=24), nullable=True))
    op.add_column("photo", sa.Column("match_score", sa.Float(), nullable=True))
    op.create_check_constraint(
        "photo_match_method_valid",
        "photo",
        "match_method is null or match_method in "
        "('gps_embedding', 'gps_only', 'embedding', 'grouped', 'new_plant', 'user')",
    )


def downgrade() -> None:
    op.drop_constraint("photo_match_method_valid", "photo", type_="check")
    op.drop_column("photo", "match_score")
    op.drop_column("photo", "match_method")
