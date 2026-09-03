from alembic import op
import sqlalchemy as sa

revision = "0009_ai_usage"
down_revision = "0008_notifications"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=150), nullable=False),
        sa.Column("agent", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_usage_provider", "ai_usage", ["provider"])
    op.create_index("ix_ai_usage_model", "ai_usage", ["model"])
    op.create_index("ix_ai_usage_agent", "ai_usage", ["agent"])
    op.create_index("ix_ai_usage_mission_id", "ai_usage", ["mission_id"])
    op.create_index("ix_ai_usage_occurred_at", "ai_usage", ["occurred_at"])


def downgrade():
    op.drop_index("ix_ai_usage_occurred_at", table_name="ai_usage")
    op.drop_index("ix_ai_usage_mission_id", table_name="ai_usage")
    op.drop_index("ix_ai_usage_agent", table_name="ai_usage")
    op.drop_index("ix_ai_usage_model", table_name="ai_usage")
    op.drop_index("ix_ai_usage_provider", table_name="ai_usage")
    op.drop_table("ai_usage")
