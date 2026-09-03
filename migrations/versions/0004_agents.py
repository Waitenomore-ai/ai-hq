from alembic import op
import sqlalchemy as sa

revision = "0004_agents"
down_revision = "0003_missions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("current_mission_id", sa.String(length=36), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("performance_metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["current_mission_id"], ["missions.id"]),
    )
    op.create_index("ix_agents_key", "agents", ["key"], unique=True)
    op.create_index("ix_agents_status", "agents", ["status"], unique=False)
    op.create_index("ix_agents_current_mission_id", "agents", ["current_mission_id"], unique=False)


def downgrade():
    op.drop_index("ix_agents_current_mission_id", table_name="agents")
    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_key", table_name="agents")
    op.drop_table("agents")
