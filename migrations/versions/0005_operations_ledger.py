from alembic import op
import sqlalchemy as sa

revision = "0005_operations_ledger"
down_revision = "0004_agents"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "operations_ledger",
        sa.Column("sequence", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("agent_key", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"]),
    )
    op.create_index("ix_operations_ledger_id", "operations_ledger", ["id"], unique=True)
    op.create_index("ix_operations_ledger_mission_id", "operations_ledger", ["mission_id"], unique=False)
    op.create_index("ix_operations_ledger_agent_key", "operations_ledger", ["agent_key"], unique=False)
    op.create_index("ix_operations_ledger_event_type", "operations_ledger", ["event_type"], unique=False)
    op.create_index("ix_operations_ledger_created_at", "operations_ledger", ["created_at"], unique=False)


def downgrade():
    op.drop_index("ix_operations_ledger_created_at", table_name="operations_ledger")
    op.drop_index("ix_operations_ledger_event_type", table_name="operations_ledger")
    op.drop_index("ix_operations_ledger_agent_key", table_name="operations_ledger")
    op.drop_index("ix_operations_ledger_mission_id", table_name="operations_ledger")
    op.drop_index("ix_operations_ledger_id", table_name="operations_ledger")
    op.drop_table("operations_ledger")
