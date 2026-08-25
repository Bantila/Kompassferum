"""consents: возраст на момент согласия

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-25

До 14 лет согласие даёт законный представитель. Раньше ученик просто выбирал
«я» или «родитель», и выбор ничем не подкреплялся.
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable: у согласий, данных до этой правки, возраста нет и взяться ему неоткуда
    op.add_column("consents", sa.Column("age_at_consent", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("consents", "age_at_consent")
