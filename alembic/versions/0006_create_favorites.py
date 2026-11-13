"""favorites 테이블 생성 (v3 회원 4단계: 관심 제품)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-14
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("food_code", sa.String(30), sa.ForeignKey("products.food_code", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        # 한 회원이 같은 제품을 두 번 저장하지 않게. (user_id, food_code) 순서라 '내 관심 제품' 찾기에도 이 인덱스를 쓴다
        sa.UniqueConstraint("user_id", "food_code", name="uq_favorites_user_product"),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("favorites")
