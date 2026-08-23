"""bot accounts: привязка чат-бота к аккаунту

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "bot_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("link_code", sa.String(length=8), nullable=True),
        sa.Column("current_task_id", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("platform", "external_id", name="uq_bot_account_platform_user"),
    )
    op.create_index("ix_bot_accounts_platform", "bot_accounts", ["platform"])
    op.create_index("ix_bot_accounts_external_id", "bot_accounts", ["external_id"])
    op.create_index("ix_bot_accounts_user_id", "bot_accounts", ["user_id"])
    op.create_index("ix_bot_accounts_link_code", "bot_accounts", ["link_code"], unique=True)


def downgrade() -> None:
    op.drop_table("bot_accounts")
