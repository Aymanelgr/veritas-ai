"""Security foundation: organizations, users, sessions, audit history, document ownership.

Existing documents and notifications are assigned to a "Default organization", so no
data is lost or hidden. Create the first admin afterwards with:
    python -m backend.manage create-user --role admin

Revision ID: 0002
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.execute("INSERT INTO organizations (id, name) VALUES (1, 'Default organization')")
    op.execute("SELECT setval('organizations_id_seq', 1)")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), index=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("target_type", sa.String(30)),
        sa.Column("target_id", sa.Integer),
        sa.Column("details", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False,
                  index=True),
    )

    op.add_column("documents", sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"),
                                         nullable=False, server_default="1"))
    op.alter_column("documents", "organization_id", server_default=None)
    op.create_index("ix_documents_organization_id", "documents", ["organization_id"])
    op.add_column("documents", sa.Column("uploaded_by_id", sa.Integer,
                                         sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("documents", sa.Column("sha256", sa.String(64)))
    op.create_index("ix_documents_sha256", "documents", ["sha256"])
    op.add_column("documents", sa.Column("size_bytes", sa.BigInteger))
    op.add_column("documents", sa.Column("content_type", sa.String(100)))

    op.add_column("notifications", sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"),
                                             nullable=False, server_default="1"))
    op.alter_column("notifications", "organization_id", server_default=None)
    op.create_index("ix_notifications_organization_id", "notifications", ["organization_id"])


def downgrade() -> None:
    op.drop_column("notifications", "organization_id")
    for column in ["content_type", "size_bytes", "sha256", "uploaded_by_id", "organization_id"]:
        op.drop_column("documents", column)
    for table in ["audit_events", "sessions", "users", "organizations"]:
        op.drop_table(table)
