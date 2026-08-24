"""test_progress: черновик теста на сервере

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

JSON_TYPE = postgresql.JSONB().with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "test_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # одна строка на ученика: два теста одновременно не проходят
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("answers", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("plan", JSON_TYPE, nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_test_progress_user_id", "test_progress", ["user_id"])


def downgrade() -> None:
    op.drop_table("test_progress")
