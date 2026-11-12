"""같은 종류 비교: (대표식품명, 기준량)이 같은 제품끼리 영양값 낮은 순으로 정렬한다."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product

# API에서 받는 정렬 기준 이름 → 테이블 칼럼
SORT_COLUMNS = {
    "sodium": Product.sodium_mg,
    "sugar": Product.sugar_g,
    "sat_fat": Product.sat_fat_g,
}
SortKey = Literal["sodium", "sugar", "sat_fat"]
Basis = Literal["100g", "100ml"]


def compare_products(
    session: Session, category: str, basis: str, sort: str, page: int, size: int
) -> tuple[int, list[Product]]:
    """같은 대표식품명 + 같은 기준량 제품의 전체 건수와, 정렬 기준 값이 낮은 순으로 한 쪽을 돌려준다."""
    column = SORT_COLUMNS[sort]
    # 기준량이 다르면(100g vs 100ml) 비교하지 않는다
    conditions = [Product.category == category, Product.basis == basis]

    total = session.scalar(select(func.count()).select_from(Product).where(*conditions))

    products = session.scalars(
        select(Product)
        .where(*conditions)
        .order_by(
            # MySQL은 오름차순에서 NULL을 맨 앞에 둔다.
            # 'column IS NULL'은 값이 있으면 0, 없으면 1이라 이것부터 정렬하면 NULL이 맨 뒤로 간다.
            column.is_(None),
            column,
            # 값이 같으면 이름, 식품코드 순 (쪽을 넘겨도 순서가 바뀌지 않게)
            Product.name,
            Product.food_code,
        )
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return total, list(products)
