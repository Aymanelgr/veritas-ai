"""Saved assistant conversations and the email intake log.

Revision ID: 0006
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("document_ids", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("conversations.id", ondelete="CASCADE"), index=True,
                  nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "email_intake",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("message_id", sa.String(500), nullable=False),
        sa.Column("sender", sa.String(320)),
        sa.Column("subject", sa.Text),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("attachments", JSONB, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("organization_id", "message_id", name="uq_email_once"),
    )


def downgrade() -> None:
    op.drop_table("email_intake")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")
