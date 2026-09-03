from alembic import op
import sqlalchemy as sa

revision = "0003_missions"
down_revision = "0002_admin_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "missions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_agent", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("priority", sa.String(length=8), nullable=False),
        sa.Column("risk", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("objectives", sa.JSON(), nullable=False),
        sa.Column("dependencies", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_state", sa.JSON(), nullable=True),
        sa.Column("approval_references", sa.JSON(), nullable=False),
        sa.Column("tool_execution_references", sa.JSON(), nullable=False),
        sa.Column("xp_reward", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_missions_owner_agent", "missions", ["owner_agent"], unique=False)
    op.create_index("ix_missions_source", "missions", ["source"], unique=False)
    op.create_index("ix_missions_status", "missions", ["status"], unique=False)


def downgrade():
    op.drop_index("ix_missions_status", table_name="missions")
    op.drop_index("ix_missions_source", table_name="missions")
    op.drop_index("ix_missions_owner_agent", table_name="missions")
    op.drop_table("missions")
