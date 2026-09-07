"""add durable recovery status

Revision ID: 0016_recovery_status
Revises: 0015_mission_leases
"""

from alembic import op
import sqlalchemy as sa


revision = "0016_recovery_status"
down_revision = "0015_mission_leases"
branch_labels = None
depends_on = None


recovery_status_result = sa.Enum(
    "unknown",
    "healthy",
    "unhealthy",
    "error",
    name="recoverystatusresult",
    native_enum=False,
    length=16,
)

recovery_incident_state = sa.Enum(
    "suspect",
    "diagnosing",
    "recovery_pending",
    "recovering",
    "verifying",
    "resolved",
    "escalated",
    name="recoveryincidentstate",
    native_enum=False,
    length=32,
)


def upgrade() -> None:
    op.create_table(
        "recovery_status",
        sa.Column("target", sa.String(length=64), primary_key=True),
        sa.Column("last_probe_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_result",
            recovery_status_result,
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("reachable", sa.Boolean(), nullable=True),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("ready", sa.Boolean(), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("active_incident_id", sa.String(length=36), nullable=True),
        sa.Column(
            "active_incident_state",
            recovery_incident_state,
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("recovery_status")
