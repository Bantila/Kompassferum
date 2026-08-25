"""consents: журнал согласий вместо текущего состояния

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-25

Строка на каждое данное согласие. Раньше строка была одна на человека и
перезаписывалась при повторном согласии — история «дал, отозвал, дал снова»
стиралась, а вместе с ней и доказательство законности обработки.
"""

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.create_index("ix_consents_user_id", "consents", ["user_id"], unique=False)


def downgrade() -> None:
    # обратно только если у каждого не больше одной строки — иначе индекс не ляжет
    op.drop_index("ix_consents_user_id", table_name="consents")
    op.create_index("ix_consents_user_id", "consents", ["user_id"], unique=True)
