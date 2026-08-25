"""consents: реестр согласий на обработку персональных данных

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # одна строка на пользователя: хранится текущее состояние, не журнал
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        # редакция документа: текст меняется, и надо знать, с чем соглашались
        sa.Column("document_version", sa.String(length=32), nullable=False),
        # self | parent — до 14 лет согласие даёт законный представитель
        sa.Column("granted_by", sa.String(length=16), nullable=False, server_default="self"),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # NULL — действует; дата — отозвано, обработка прекращена
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consents_user_id", "consents", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.drop_table("consents")
