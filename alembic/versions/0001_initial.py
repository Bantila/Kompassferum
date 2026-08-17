"""initial schema: users, test_results, recommendations

Revision ID: 0001
Revises:
Create Date: 2026-08-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("max_user_id", sa.String(length=128), nullable=False),
        sa.Column(
            "role",
            sa.Enum("student", "teacher", name="user_role"),
            nullable=False,
            server_default="student",
        ),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("school_class", sa.String(length=16), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_max_user_id", "users", ["max_user_id"], unique=True)
    op.create_index("ix_users_school_class", "users", ["school_class"])

    op.create_table(
        "test_results",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("raw_answers", postgresql.JSONB(), nullable=False),
        sa.Column("computed_scores", postgresql.JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_test_results_user_id", "test_results", ["user_id"])

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "test_result_id",
            sa.Uuid(),
            sa.ForeignKey("test_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ai_response", postgresql.JSONB(), nullable=False),
        sa.Column("professions", postgresql.JSONB(), nullable=False),
        sa.Column("model_used", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_recommendations_test_result_id", "recommendations", ["test_result_id"], unique=True
    )


def downgrade() -> None:
    op.drop_table("recommendations")
    op.drop_table("test_results")
    op.drop_table("users")
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
