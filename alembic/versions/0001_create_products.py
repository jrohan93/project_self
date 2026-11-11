"""products 테이블 생성

Revision ID: 0001
Revises:
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("food_code", sa.String(30), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("maker", sa.String(255), nullable=True),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("basis", sa.String(10), nullable=False),
        sa.Column("energy_kcal", sa.Numeric(10, 2), nullable=True),
        sa.Column("sodium_mg", sa.Numeric(10, 2), nullable=True),
        sa.Column("sugar_g", sa.Numeric(10, 2), nullable=True),
        sa.Column("sat_fat_g", sa.Numeric(10, 2), nullable=True),
        mysql_charset="utf8mb4",
    )


def downgrade() -> None:
    op.drop_table("products")
