from alembic import op
import sqlalchemy as sa

revision = "0006_approvals"
down_revision = "0005_operations_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("mission_id", sa.String(length=36), nullable=False),
        sa.Column("requester_agent", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=False),
        sa.Column("action_plan", sa.JSON(), nullable=False),
        sa.Column("action_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"]),
    )
    op.create_index("ix_approval_requests_mission_id", "approval_requests", ["mission_id"])
    op.create_index("ix_approval_requests_action_fingerprint", "approval_requests", ["action_fingerprint"])
    op.create_index("ix_approval_requests_state", "approval_requests", ["state"])

    op.create_table(
        "scoped_approval_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("target", sa.String(length=255), nullable=False),
        sa.Column("risk", sa.String(length=16), nullable=False),
        sa.Column("conditions", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_execution_count", sa.Integer(), nullable=True),
        sa.Column("execution_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_scoped_approval_rules_action", "scoped_approval_rules", ["action"])
    op.create_index("ix_scoped_approval_rules_target", "scoped_approval_rules", ["target"])


def downgrade():
    op.drop_index("ix_scoped_approval_rules_target", table_name="scoped_approval_rules")
    op.drop_index("ix_scoped_approval_rules_action", table_name="scoped_approval_rules")
    op.drop_table("scoped_approval_rules")
    op.drop_index("ix_approval_requests_state", table_name="approval_requests")
    op.drop_index("ix_approval_requests_action_fingerprint", table_name="approval_requests")
    op.drop_index("ix_approval_requests_mission_id", table_name="approval_requests")
    op.drop_table("approval_requests")
