"""refresh_tokens 테이블 생성 (v3 회원 2단계)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime, nullable=False),
        sa.Column("used_at", sa.DateTime, nullable=True),
        sa.Column("revoked_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        mysql_charset="utf8mb4",
    )
    # 로그아웃(묶음 끊기)에서 family_id로 찾는다. user_id는 외래 키라 MySQL이 인덱스를 자동으로 만든다
    op.create_index("ix_refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def downgrade() -> None:
    op.drop_table("refresh_tokens")
