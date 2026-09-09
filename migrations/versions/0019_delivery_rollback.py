"""add delivery rollback identity

Revision ID: 0019_delivery_rollback
Revises: 0018_delivery_release
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_delivery_rollback"
down_revision = "0018_delivery_release"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "rollback_release_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "rolled_back_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mission_deliveries", "rolled_back_at")
    op.drop_column("mission_deliveries", "rollback_release_id")