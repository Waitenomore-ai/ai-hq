from alembic import op
import sqlalchemy as sa

revision = "0007_knowledge_core"
down_revision = "0006_approvals"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "knowledge_memories",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("owner_scope", sa.String(length=128), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("verification_state", sa.String(length=32), nullable=False),
        sa.Column("sensitivity", sa.String(length=32), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("allowed_agents", sa.JSON(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("temporary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("contradicts_memory_id", sa.String(length=36), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["contradicts_memory_id"], ["knowledge_memories.id"]),
    )
    op.create_index("ix_knowledge_memories_category", "knowledge_memories", ["category"])
    op.create_index("ix_knowledge_memories_owner_scope", "knowledge_memories", ["owner_scope"])
    op.create_index(
        "ix_knowledge_memories_verification_state", "knowledge_memories", ["verification_state"]
    )
    op.create_index("ix_knowledge_memories_visibility", "knowledge_memories", ["visibility"])
    op.create_index("ix_knowledge_memories_expires_at", "knowledge_memories", ["expires_at"])
    op.create_index(
        "ix_knowledge_memories_contradicts_memory_id",
        "knowledge_memories",
        ["contradicts_memory_id"],
    )
    op.create_index("ix_knowledge_memories_deleted_at", "knowledge_memories", ["deleted_at"])
    op.create_index("ix_knowledge_memories_created_at", "knowledge_memories", ["created_at"])


def downgrade():
    op.drop_index("ix_knowledge_memories_created_at", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_deleted_at", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_contradicts_memory_id", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_expires_at", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_visibility", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_verification_state", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_owner_scope", table_name="knowledge_memories")
    op.drop_index("ix_knowledge_memories_category", table_name="knowledge_memories")
    op.drop_table("knowledge_memories")
