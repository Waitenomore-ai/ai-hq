"""add delivery publication identity

Revision ID: 0016_delivery_publication
Revises: 0015_mission_leases
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_delivery_publication"
down_revision = "0015_mission_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "published_branch",
            sa.String(length=255),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "published_commit",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "published_tree",
            sa.String(length=40),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mission_deliveries", "published_at")
    op.drop_column("mission_deliveries", "published_tree")
    op.drop_column("mission_deliveries", "published_commit")
    op.drop_column("mission_deliveries", "published_branch")
