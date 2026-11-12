"""제품 검색: 이름 검색 + 대표식품명 필터 + 페이지 나누기."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Product


def search_products(
    session: Session, q: str, category: str | None, page: int, size: int
) -> tuple[int, list[Product]]:
    """조건에 맞는 전체 건수와 해당 페이지의 제품 목록을 돌려준다."""
    conditions = []
    if q:
        # 이름 어디에든 q가 들어 있으면 찾는다 (LIKE '%q%').
        # autoescape=True: 사용자가 입력한 %, _ 를 와일드카드가 아닌 글자 그대로 찾는다.
        conditions.append(Product.name.contains(q, autoescape=True))
    if category:
        # 종류 구분은 이름이 아니라 대표식품명으로 (참치 → 참치김밥이 섞이지 않게)
        conditions.append(Product.category == category)

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
