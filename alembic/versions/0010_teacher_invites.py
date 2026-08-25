"""teacher_invites: подтверждение роли педагога кодом приглашения

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
        "teacher_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        # NULL — загрузочный код из консоли: первого педагога пригласить некому
        sa.Column(
            "created_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("note", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "used_by_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )
    # уникальность на коде, а не только индекс: две одинаковые строки означали
    # бы, что одним кодом регистрируются двое
    op.create_index("ix_teacher_invites_code", "teacher_invites", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_teacher_invites_code", table_name="teacher_invites")
    op.drop_table("teacher_invites")
