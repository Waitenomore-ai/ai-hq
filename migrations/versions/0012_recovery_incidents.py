"""add recovery incidents and attempts

Revision ID: 0012_recovery_incidents
Revises: 0011_sysadmin_chat
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_recovery_incidents"
down_revision = "0011_sysadmin_chat"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recovery_incidents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("active_key", sa.String(length=128), nullable=True),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "first_failure_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_failure_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_observed_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("diagnostics", sa.JSON(), nullable=False),
        sa.Column("verification", sa.JSON(), nullable=False),
        sa.Column(
            "recovery_mission_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "last_recovery_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("escalation_reason", sa.Text(), nullable=True),
        sa.Column(
            "resolved_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["recovery_mission_id"],
            ["missions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "active_key",
            name="uq_recovery_incidents_active_key",
        ),
    )
    op.create_index(
        "ix_recovery_incidents_target",
        "recovery_incidents",
        ["target"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_incidents_component",
        "recovery_incidents",
        ["component"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_incidents_state",
        "recovery_incidents",
        ["state"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_incidents_recovery_mission_id",
        "recovery_incidents",
        ["recovery_mission_id"],
        unique=False,
    )

    op.create_table(
        "recovery_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
        sa.Column("target", sa.String(length=64), nullable=False),
        sa.Column("component", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "simulated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["recovery_incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recovery_attempts_incident_id",
        "recovery_attempts",
        ["incident_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attempts_target",
        "recovery_attempts",
        ["target"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attempts_component",
        "recovery_attempts",
        ["component"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attempts_mission_id",
        "recovery_attempts",
        ["mission_id"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attempts_attempted_at",
        "recovery_attempts",
        ["attempted_at"],
        unique=False,
    )
    op.create_index(
        "ix_recovery_attempts_simulated",
        "recovery_attempts",
        ["simulated"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recovery_attempts_simulated",
        table_name="recovery_attempts",
    )
    op.drop_index(
        "ix_recovery_attempts_attempted_at",
        table_name="recovery_attempts",
    )
    op.drop_index(
        "ix_recovery_attempts_mission_id",
        table_name="recovery_attempts",
    )
    op.drop_index(
        "ix_recovery_attempts_component",
        table_name="recovery_attempts",
    )
    op.drop_index(
        "ix_recovery_attempts_target",
        table_name="recovery_attempts",
    )
    op.drop_index(
        "ix_recovery_attempts_incident_id",
        table_name="recovery_attempts",
    )
    op.drop_table("recovery_attempts")

    op.drop_index(
        "ix_recovery_incidents_recovery_mission_id",
        table_name="recovery_incidents",
    )
    op.drop_index(
        "ix_recovery_incidents_state",
        table_name="recovery_incidents",
    )
    op.drop_index(
        "ix_recovery_incidents_component",
        table_name="recovery_incidents",
    )
    op.drop_index(
        "ix_recovery_incidents_target",
        table_name="recovery_incidents",
    )
    op.drop_table("recovery_incidents")
