"""대체 제품 추천: 같은 대표식품명 + 같은 기준량에서 나트륨 또는 당류가 더 낮은 제품."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product

# API에서 받는 추천 기준 이름 → 테이블 칼럼
RECOMMEND_COLUMNS = {
    "sodium": Product.sodium_mg,
    "sugar": Product.sugar_g,
}
RecommendKey = Literal["sodium", "sugar"]


def find_alternatives(
    session: Session, product: Product, by: str, limit: int
) -> tuple[int, list[Product]]:
    """기준 제품보다 고른 영양값이 낮은 제품의 전체 수와, 낮은 순으로 limit개를 돌려준다."""
    column = RECOMMEND_COLUMNS[by]
    value = getattr(product, column.key)  # 기준 제품의 값 (예: product.sodium_mg)
    if value is None:
        # 기준 값이 정보 없음이면 '더 낮다'고 말할 수 없다
        return 0, []

    conditions = [
        Product.category == product.category,
        Product.basis == product.basis,  # 기준량이 다르면 비교하지 않는다
        # 값이 NULL인 후보는 'NULL < 값'이 참이 아니므로 여기서 저절로 빠진다.
        # 기준 제품 자신도 같은 값이라 빠진다.
        column < value,
    ]
    if by == "sugar" and product.sodium_mg is not None:
        # 당은 줄었는데 더 짜지면 건강한 대체가 아니므로 나트륨이 기준 제품 이하인 것만.
        # 나트륨이 NULL인 후보는 더 짜지 않다고 말할 수 없어서 저절로 빠진다.
        # 기준 제품의 나트륨이 NULL이면 비교할 값이 없어 이 조건은 걸지 않는다.
        conditions.append(Product.sodium_mg <= product.sodium_mg)

    total = session.scalar(select(func.count()).select_from(Product).where(*conditions))

    products = session.scalars(
        select(Product)
        .where(*conditions)
        # 가장 많이 낮은 것부터. 값이 같으면 이름, 식품코드 순
        .order_by(column, Product.name, Product.food_code)
        .limit(limit)
    ).all()
    return total, list(products)
