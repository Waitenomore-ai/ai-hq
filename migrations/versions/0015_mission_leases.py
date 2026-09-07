"""add mission worker leases

Revision ID: 0015_mission_leases
Revises: 0014_recovery_incidents
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_mission_leases"
down_revision = "0014_recovery_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "missions",
        sa.Column(
            "lease_owner",
            sa.String(length=128),
            nullable=True,
        ),
    )

    op.add_column(
        "missions",
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "missions",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_index(
        "ix_missions_lease_owner",
        "missions",
        ["lease_owner"],
        unique=False,
    )

    op.create_index(
        "ix_missions_lease_expires_at",
        "missions",
        ["lease_expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_missions_lease_expires_at",
        table_name="missions",
    )

    op.drop_index(
        "ix_missions_lease_owner",
        table_name="missions",
    )

    op.drop_column(
        "missions",
        "attempt_count",
    )

    op.drop_column(
        "missions",
        "lease_expires_at",
    )

    op.drop_column(
        "missions",
        "lease_owner",
    )
