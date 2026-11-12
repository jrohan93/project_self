"""제품 검색: 제품 이름 또는 회사 이름 검색 + 대표식품명·기준량 필터 + 영양값 상한 + 페이지 나누기."""

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product

# 검색어를 어느 칼럼에서 찾을지
SEARCH_TARGETS = {
    "name": Product.name,    # 제품 이름
    "maker": Product.maker,  # 회사 이름 (제조사, 없으면 수입사)
}
SearchTarget = Literal["name", "maker"]

# 영양값 상한 조건 이름 → 칼럼 ("이 값 이하인 제품만")
MAX_COLUMNS = {
    "max_kcal": Product.energy_kcal,
    "max_sodium": Product.sodium_mg,
    "max_sugar": Product.sugar_g,
    "max_sat_fat": Product.sat_fat_g,
}


def search_products(
    session: Session,
    q: str,
    category: str | None,
    page: int,
    size: int,
    target: str = "name",
    basis: str | None = None,
    max_values: dict[str, float] | None = None,
) -> tuple[int, list[Product]]:
    """조건에 맞는 전체 건수와 해당 페이지의 제품 목록을 돌려준다.

    max_values: {"max_sodium": 500, ...}처럼 '이 값 이하'로 거를 영양값 (기준량당 값).
    """
    conditions = []
    if q:
        # 고른 칼럼 어디에든 q가 들어 있으면 찾는다 (LIKE '%q%').
        # autoescape=True: 사용자가 입력한 %, _ 를 와일드카드가 아닌 글자 그대로 찾는다.
        conditions.append(SEARCH_TARGETS[target].contains(q, autoescape=True))
    if category:
        # 종류 구분은 이름이 아니라 대표식품명으로 (참치 → 참치김밥이 섞이지 않게)
        conditions.append(Product.category == category)
    if basis:
        conditions.append(Product.basis == basis)
    for key, limit in (max_values or {}).items():
        # 값이 NULL(정보 없음)인 제품은 'NULL <= 값'이 참이 아니라서 저절로 빠진다.
        # 조건에 맞는지 알 수 없으므로 보여주지 않는다.
        conditions.append(MAX_COLUMNS[key] <= limit)

    total = session.scalar(select(func.count()).select_from(Product).where(*conditions))

    products = session.scalars(
        select(Product)
        .where(*conditions)
        # 페이지를 넘겨도 순서가 바뀌지 않게, 이름이 같으면 식품코드로 한 번 더 정렬
        .order_by(Product.name, Product.food_code)
        .offset((page - 1) * size)
        .limit(size)
    ).all()
    return total, list(products)
