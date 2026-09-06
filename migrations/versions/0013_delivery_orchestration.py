"""add persisted developer qa delivery workflow

Revision ID: 0013_delivery_orchestration
Revises: 0011_sysadmin_chat
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_delivery_orchestration"
down_revision = "0011_sysadmin_chat"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mission_deliveries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column(
            "stage",
            sa.Enum(
                "DEVELOPER",
                "QA",
                "WAITING_APPROVAL",
                name="deliverystage",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("change_ref", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("changed_files", sa.JSON(), nullable=False),
        sa.Column("developer_evidence", sa.JSON(), nullable=False),
        sa.Column(
            "qa_result",
            sa.Enum(
                "PASSED",
                "FAILED",
                name="qaresult",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("qa_evidence", sa.JSON(), nullable=True),
        sa.Column(
            "approval_reference",
            sa.String(length=64),
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
            ["mission_id"],
            ["missions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mission_id"),
        sa.UniqueConstraint("approval_reference"),
    )

    op.create_index(
        op.f("ix_mission_deliveries_mission_id"),
        "mission_deliveries",
        ["mission_id"],
        unique=True,
    )

    op.create_index(
        op.f("ix_mission_deliveries_stage"),
        "mission_deliveries",
        ["stage"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        op.f("ix_mission_deliveries_stage"),
        table_name="mission_deliveries",
    )

    op.drop_index(
        op.f("ix_mission_deliveries_mission_id"),
        table_name="mission_deliveries",
    )

    op.drop_table("mission_deliveries")
