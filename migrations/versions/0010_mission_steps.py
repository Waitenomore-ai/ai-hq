"""add persisted mission plan steps

Revision ID: 0010_mission_steps
Revises: 0009_ai_usage
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_mission_steps"
down_revision = "0009_ai_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mission_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("tool_arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_state", sa.JSON(), nullable=True),
        sa.Column("approval_reference", sa.String(length=64), nullable=True),
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
            ["mission_id"],
            ["missions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mission_id",
            "position",
            name="uq_mission_steps_mission_position",
        ),
    )

    op.create_index(
        "ix_mission_steps_mission_id",
        "mission_steps",
        ["mission_id"],
        unique=False,
    )

    op.create_index(
        "ix_mission_steps_status",
        "mission_steps",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_mission_steps_status",
        table_name="mission_steps",
    )

    op.drop_index(
        "ix_mission_steps_mission_id",
        table_name="mission_steps",
    )

    op.drop_table("mission_steps")
