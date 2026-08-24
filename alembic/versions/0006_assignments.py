"""class assignments: задания классу от педагога

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "class_assignments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("school_classes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "teacher_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subjects", postgresql.JSONB(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("difficulty", sa.String(length=16), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_class_assignments_class_id", "class_assignments", ["class_id"])
    op.create_index("ix_class_assignments_created_at", "class_assignments", ["created_at"])


def downgrade() -> None:
    op.drop_table("class_assignments")
