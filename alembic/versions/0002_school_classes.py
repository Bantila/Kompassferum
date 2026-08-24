"""school classes + join codes

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "school_classes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column(
            "teacher_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("join_code", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_school_classes_teacher_id", "school_classes", ["teacher_id"])
    op.create_index("ix_school_classes_join_code", "school_classes", ["join_code"], unique=True)

    op.add_column("users", sa.Column("class_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_users_class_id", "users", "school_classes", ["class_id"], ["id"], ondelete="SET NULL"
    )
    op.create_index("ix_users_class_id", "users", ["class_id"])


def downgrade() -> None:
    op.drop_index("ix_users_class_id", table_name="users")
    op.drop_constraint("fk_users_class_id", "users", type_="foreignkey")
    op.drop_column("users", "class_id")
    op.drop_table("school_classes")
