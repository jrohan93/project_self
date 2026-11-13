"""users 테이블 생성 (v3 회원 1단계)

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("users")
