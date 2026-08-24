"""test_results.integrity: оценка доверия к ответам

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-24
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # server_default нужен существующим строкам: у прежних прохождений проверки
    # не было, и без значения по умолчанию они получили бы NULL вместо объекта
    op.add_column(
        "test_results",
        sa.Column(
            "integrity",
            postgresql.JSONB().with_variant(sa.JSON(), "sqlite"),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("test_results", "integrity")
