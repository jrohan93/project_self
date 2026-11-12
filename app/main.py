"""FastAPI 앱. 실행: uvicorn app.main:app --reload"""

from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session, sessionmaker

from app.compare import Basis, SortKey, compare_products
from app.db import make_engine
from app.models import Product
from app.recommend import RecommendKey, find_alternatives
from app.schemas import AlternativesResult, CompareResult, ProductItem, SearchResult
from app.search import search_products

app = FastAPI(title="가공식품 영양 비교 검색")

# 엔진은 앱 전체에서 하나만 만든다 (연결은 실제로 쿼리할 때 맺어짐)
SessionLocal = sessionmaker(make_engine())


def get_session() -> Iterator[Session]:
    # 요청 하나마다 세션을 열고, 응답이 끝나면 닫는다
    with SessionLocal() as session:
        yield session


@app.get("/api/products", response_model=SearchResult)
def list_products(
    q: str = Query("", max_length=100, description="제품 이름에 들어간 글자"),
    category: str | None = Query(None, max_length=50, description="대표식품명 (예: 간장)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> SearchResult:
    q = q.strip()
    if not q and not category:
        # 조건 없이 33만 건 전체를 정렬하는 요청은 받지 않는다
        raise HTTPException(status_code=400, detail="검색어나 대표식품명 중 하나는 입력해 주세요.")

    total, products = search_products(session, q, category, page, size)
    return SearchResult(
        total=total,
        page=page,
        size=size,
        items=[ProductItem.model_validate(p) for p in products],
    )


@app.get("/api/products/{food_code}", response_model=ProductItem)
def get_product(food_code: str, session: Session = Depends(get_session)) -> ProductItem:
    # 식품코드가 기본키라서 session.get으로 한 건을 바로 찾는다
    product = session.get(Product, food_code)
    if product is None:
        raise HTTPException(status_code=404, detail="해당 제품이 없어요.")
    return ProductItem.model_validate(product)


@app.get("/api/products/{food_code}/alternatives", response_model=AlternativesResult)
def get_alternatives(
    food_code: str,
    by: RecommendKey = Query("sodium", description="이 값이 더 낮은 제품을 찾는다"),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> AlternativesResult:
    product = session.get(Product, food_code)
    if product is None:
        raise HTTPException(status_code=404, detail="해당 제품이 없어요.")

    total, alternatives = find_alternatives(session, product, by, limit)
    return AlternativesResult(
        product=ProductItem.model_validate(product),
        by=by,
        total=total,
        items=[ProductItem.model_validate(p) for p in alternatives],
    )


@app.get("/api/compare", response_model=CompareResult)
def compare(
    category: str = Query(..., min_length=1, max_length=50, description="대표식품명 (예: 간장)"),
    basis: Basis = Query(..., description="기준량. 같은 기준량끼리만 비교한다"),
    sort: SortKey = Query("sodium", description="낮은 순으로 정렬할 영양값"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> CompareResult:
    total, products = compare_products(session, category, basis, sort, page, size)
    return CompareResult(
        category=category,
        basis=basis,
        sort=sort,
        total=total,
        page=page,
        size=size,
        items=[ProductItem.model_validate(p) for p in products],
    )
