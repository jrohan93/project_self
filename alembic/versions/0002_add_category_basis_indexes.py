"""(대표식품명, 기준량, 영양값) 인덱스 추가 (v2 성능 1단계)

같은 종류 비교, 대체 제품 추천, 대표식품명 검색이 32만 행 전체를 읽지 않고
그 (대표식품명, 기준량) 묶음만 읽게 한다.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# (인덱스 이름, 세 번째 칼럼 = 그 묶음 안에서 낮은 순으로 찾는 영양값)
INDEXES = [
    ("ix_products_category_basis_sodium", "sodium_mg"),
    ("ix_products_category_basis_sugar", "sugar_g"),
    ("ix_products_category_basis_sat_fat", "sat_fat_g"),
]


def upgrade() -> None:
    for name, nutrient in INDEXES:
        op.create_index(name, "products", ["category", "basis", nutrient])


def downgrade() -> None:
    for name, _ in INDEXES:
        op.drop_index(name, table_name="products")
