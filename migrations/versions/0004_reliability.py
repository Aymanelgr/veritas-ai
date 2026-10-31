"""Reliable processing, idempotent findings, reviewer corrections, alert delivery tracking.

Revision ID: 0004
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Findings: what kind of result, money impact, and a fingerprint so reprocessing updates
    # the same finding (keeping its review) instead of creating a duplicate.
    op.add_column("findings", sa.Column("kind", sa.String(30), nullable=False, server_default="discrepancy"))
    op.execute("UPDATE findings SET kind = 'ok' WHERE verdict = 'supported'")
    op.add_column("findings", sa.Column("impact", sa.Numeric(18, 4)))
    op.add_column("findings", sa.Column("currency", sa.String(3)))
    op.add_column("findings", sa.Column("subject", sa.Text))
    op.add_column("findings", sa.Column("fingerprint", sa.String(64)))
    op.create_index("ix_findings_fingerprint", "findings", ["fingerprint"])
    op.add_column("findings", sa.Column("rule_version", sa.String(40)))
    op.add_column("findings", sa.Column("model_versions", JSONB, nullable=False, server_default="{}"))
    op.add_column("findings", sa.Column("attachments", JSONB, nullable=False, server_default="[]"))
    op.add_column("findings", sa.Column("updated_at", sa.DateTime(timezone=True)))

    op.add_column("documents", sa.Column("stage", sa.String(30)))
    op.add_column("documents", sa.Column("progress", JSONB, nullable=False, server_default="{}"))
    op.add_column("documents", sa.Column("cache_key", sa.String(64)))
    op.add_column("documents", sa.Column("processing_started_at", sa.DateTime(timezone=True)))
    op.add_column("documents", sa.Column("processed_at", sa.DateTime(timezone=True)))

    op.create_table(
        "processing_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), index=True,
                  nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stages", JSONB, nullable=False, server_default="[]"),
        sa.Column("error", sa.Text),
        sa.Column("config_version", sa.String(400)),
    )
    op.create_table(
        "corrections",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="CASCADE"), index=True,
                  nullable=False),
        sa.Column("field_path", sa.String(200), nullable=False),
        sa.Column("original_value", JSONB),
        sa.Column("new_value", JSONB),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "alert_deliveries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), index=True, nullable=False),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(30), nullable=False),  # critical | summary | reminder | test
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),  # queued | sent | preview | failed | skipped
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("recipients", JSONB, nullable=False, server_default="[]"),
        sa.Column("summary", sa.Text),
        sa.Column("last_error", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "kind", "fingerprint", name="uq_alert_once"),
    )
    op.create_table(
        "organization_settings",
        sa.Column("organization_id", sa.Integer, sa.ForeignKey("organizations.id"), primary_key=True),
        sa.Column("alert_recipients", JSONB, nullable=False, server_default="[]"),
        sa.Column("email_mode", sa.String(10), nullable=False, server_default="preview"),  # off | preview | send
        sa.Column("alert_min_severity", sa.String(10), nullable=False, server_default="critical"),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    for table in ["organization_settings", "alert_deliveries", "corrections", "processing_runs"]:
        op.drop_table(table)
    for column in ["processed_at", "processing_started_at", "cache_key", "progress", "stage"]:
        op.drop_column("documents", column)
    for column in ["updated_at", "attachments", "model_versions", "rule_version", "fingerprint", "subject",
                   "currency", "impact", "kind"]:
        op.drop_column("findings", column)
