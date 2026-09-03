from alembic import op
import sqlalchemy as sa

revision = "0002_admin_sessions"
down_revision = "0001_system_state"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("csrf_token", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_admin_sessions_token_digest", "admin_sessions", ["token_digest"], unique=True)
    op.create_index("ix_admin_sessions_expires_at", "admin_sessions", ["expires_at"], unique=False)


def downgrade():
    op.drop_index("ix_admin_sessions_expires_at", table_name="admin_sessions")
    op.drop_index("ix_admin_sessions_token_digest", table_name="admin_sessions")
    op.drop_table("admin_sessions")
