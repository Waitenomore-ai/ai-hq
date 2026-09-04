"""add persisted sysadmin chat

Revision ID: 0011_sysadmin_chat
Revises: 0010_mission_steps
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_sysadmin_chat"
down_revision = "0010_mission_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_session_id", sa.String(length=36), nullable=False),
        sa.Column(
            "agent_key",
            sa.String(length=64),
            nullable=False,
            server_default="sysadmin",
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
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_chat_conversations_owner_session_id",
        "chat_conversations",
        ["owner_session_id"],
        unique=False,
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("mission_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["chat_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "conversation_id",
            "position",
            name="uq_chat_messages_conversation_position",
        ),
    )
    op.create_index(
        "ix_chat_messages_conversation_id",
        "chat_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        "ix_chat_messages_mission_id",
        "chat_messages",
        ["mission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_chat_messages_mission_id",
        table_name="chat_messages",
    )
    op.drop_index(
        "ix_chat_messages_conversation_id",
        table_name="chat_messages",
    )
    op.drop_table("chat_messages")

    op.drop_index(
        "ix_chat_conversations_owner_session_id",
        table_name="chat_conversations",
    )
    op.drop_table("chat_conversations")
