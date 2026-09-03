from alembic import op
import sqlalchemy as sa

revision = "0001_system_state"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "system_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("operating_mode", sa.String(length=16), nullable=False, server_default="safe"),
        sa.Column("simulation_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table("system_state")
