"""Matching and document identity: link statuses, manual decisions, duplicates, revisions, overrides.

Existing links become "proposed" (made by reference or content, nobody confirmed them yet).

Revision ID: 0003
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # What the user said about the document (type, language, currency, date order),
    # which wins over automatic detection.
    op.add_column("documents", sa.Column("overrides", JSONB, nullable=False, server_default="{}"))
    op.add_column("documents", sa.Column("language", sa.String(10)))
    # Identity: type + issuing organization + number ("purchase_order|coastline fabrication|PO20269901").
    op.add_column("documents", sa.Column("identity_key", sa.String(400)))
    op.create_index("ix_documents_identity_key", "documents", ["identity_key"])
    # The same file uploaded twice points to the first copy and is not processed again.
    op.add_column("documents", sa.Column("duplicate_of_id", sa.Integer,
                                         sa.ForeignKey("documents.id", ondelete="SET NULL")))
    # A changed document with the same identity is a new revision of the older one.
    op.add_column("documents", sa.Column("supersedes_id", sa.Integer,
                                         sa.ForeignKey("documents.id", ondelete="SET NULL")))
    op.add_column("documents", sa.Column("revision", sa.Integer, nullable=False, server_default="1"))
    op.add_column("documents", sa.Column("is_current", sa.Boolean, nullable=False, server_default=sa.true()))

    op.add_column("links", sa.Column("status", sa.String(20), nullable=False, server_default="proposed"))
    op.add_column("links", sa.Column("method", sa.String(20), nullable=False, server_default="reference"))
    op.add_column("links", sa.Column("note", sa.Text))
    op.add_column("links", sa.Column("decided_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.add_column("links", sa.Column("decided_at", sa.DateTime(timezone=True)))
    op.add_column("links", sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                                     nullable=False))
    op.create_unique_constraint("uq_links_pair", "links", ["invoice_id", "purchase_order_id"])


def downgrade() -> None:
    op.drop_constraint("uq_links_pair", "links")
    for column in ["created_at", "decided_at", "decided_by_id", "note", "method", "status"]:
        op.drop_column("links", column)
    for column in ["is_current", "revision", "supersedes_id", "duplicate_of_id", "identity_key", "language", "overrides"]:
        op.drop_column("documents", column)
