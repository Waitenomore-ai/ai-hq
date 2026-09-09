"""add delivery release identity

Revision ID: 0018_delivery_release
Revises: 0017_delivery_publication
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_delivery_release"
down_revision = "0017_delivery_publication"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "deployment_release_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "deployment_prior_release_id",
            sa.String(length=128),
            nullable=True,
        ),
    )
    op.add_column(
        "mission_deliveries",
        sa.Column(
            "deployed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("mission_deliveries", "deployed_at")
    op.drop_column("mission_deliveries", "deployment_prior_release_id")
    op.drop_column("mission_deliveries", "deployment_release_id")