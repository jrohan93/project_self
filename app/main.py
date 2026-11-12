"""FastAPI 앱. 실행: uvicorn app.main:app --reload"""

from collections.abc import Iterator

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session, sessionmaker

from app.db import make_engine
from app.schemas import ProductItem, SearchResult
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
