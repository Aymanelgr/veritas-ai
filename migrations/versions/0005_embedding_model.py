"""Remember which embedding model produced each passage, so a model change can re-index them.

Existing passages were made with all-MiniLM-L6-v2.

Revision ID: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("embedding_model", sa.String(200), nullable=False,
                                      server_default="sentence-transformers/all-MiniLM-L6-v2"))
    op.alter_column("chunks", "embedding_model", server_default=None)


def downgrade() -> None:
    op.drop_column("chunks", "embedding_model")
