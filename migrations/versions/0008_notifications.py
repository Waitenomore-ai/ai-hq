from alembic import op
import sqlalchemy as sa

revision = "0008_notifications"
down_revision = "0007_knowledge_core"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=True),
        sa.Column("source_id", sa.String(length=128), nullable=True),
        sa.Column("group_key", sa.String(length=255), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notifications_severity", "notifications", ["severity"])
    op.create_index("ix_notifications_source_type", "notifications", ["source_type"])
    op.create_index("ix_notifications_source_id", "notifications", ["source_id"])
    op.create_index("ix_notifications_group_key", "notifications", ["group_key"])
    op.create_index("ix_notifications_last_occurred_at", "notifications", ["last_occurred_at"])
    op.create_index("ix_notifications_read_at", "notifications", ["read_at"])
    op.create_index("ix_notifications_dismissed_at", "notifications", ["dismissed_at"])


def downgrade():
    op.drop_index("ix_notifications_dismissed_at", table_name="notifications")
    op.drop_index("ix_notifications_read_at", table_name="notifications")
    op.drop_index("ix_notifications_last_occurred_at", table_name="notifications")
    op.drop_index("ix_notifications_group_key", table_name="notifications")
    op.drop_index("ix_notifications_source_id", table_name="notifications")
    op.drop_index("ix_notifications_source_type", table_name="notifications")
    op.drop_index("ix_notifications_severity", table_name="notifications")
    op.drop_table("notifications")
