"""FastAPI 앱. 실행: uvicorn app.main:app --reload

/api/... 는 JSON API, 나머지(/, /products/..., /compare)는 Jinja2로 만든 HTML 화면.
"""

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import auth, cache, refresh
from app.compare import Basis, SortKey, compare_products
from app.db import make_engine
from app.models import Product, User
from app.recommend import RECOMMEND_COLUMNS, RecommendKey, find_alternatives
from app.schemas import (AlternativesResult, CompareResult, LoginRequest, ProductItem, RefreshRequest, SearchResult,
                         SignupRequest, TokenResponse, UserItem)
from app.search import SearchTarget, search_products

app = FastAPI(title="가공식품 영양 비교 검색")

# 엔진은 앱 전체에서 하나만 만든다 (연결은 실제로 쿼리할 때 맺어짐)
SessionLocal = sessionmaker(make_engine())

PAGE_SIZES = (5, 10, 20, 30)  # 화면 한 쪽에 보여줄 제품 수 (고를 수 있는 값)
DEFAULT_PAGE_SIZE = 20
ALTERNATIVES_ON_DETAIL = 5  # 상세 화면에 보여줄 대체 제품 수


def format_nutrient(value: float | None, unit: str) -> str:
    """영양값 표시: 정보 없음(None)은 0이 아니라 글자로, 숫자는 쉼표 + 불필요한 소수점 0 제거."""
    if value is None:
        # 흐린 색으로 보이게 span으로 감싼다. Markup은 '이미 안전한 HTML'이라 이스케이프되지 않는다
        return Markup('<span class="na">정보 없음</span>')
    text = f"{value:,.2f}".rstrip("0").rstrip(".")  # 6454.00 → 6,454 / 0.40 → 0.4
    return f"{text} {unit}"


# 템플릿은 자동 이스케이프가 켜져 있어서 제품 이름에 <, > 같은 글자가 있어도 HTML로 실행되지 않는다
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["nutrient"] = format_nutrient


def get_session() -> Iterator[Session]:
    # 요청 하나마다 세션을 열고, 응답이 끝나면 닫는다
    with SessionLocal() as session:
        yield session


# ---------------- 결과 만들기 (Redis 캐시) ----------------
# API와 화면이 같이 쓴다. 같은 조건이면 캐시(app/cache.py)에서 꺼내고, 없으면 DB에서 읽어 저장한다.

def search_result(session: Session, q: str, category: str | None, page: int, size: int,
                  target: str = "name", basis: str | None = None,
                  max_values: dict[str, float] | None = None) -> SearchResult:
    max_values = max_values or {}
    key = cache.make_key("search", q=q, category=category, page=page, size=size,
                         target=target, basis=basis, **max_values)

    def compute() -> SearchResult:
        total, products = search_products(session, q, category, page, size, target, basis, max_values)
        return SearchResult(total=total, page=page, size=size,
                            items=[ProductItem.model_validate(p) for p in products])

    return cache.get_or_set(key, SearchResult, compute)


def compare_result(session: Session, category: str, basis: str, sort: str, page: int, size: int) -> CompareResult:
    key = cache.make_key("compare", category=category, basis=basis, sort=sort, page=page, size=size)

    def compute() -> CompareResult:
        total, products = compare_products(session, category, basis, sort, page, size)
        return CompareResult(category=category, basis=basis, sort=sort, total=total, page=page, size=size,
                             items=[ProductItem.model_validate(p) for p in products])

    return cache.get_or_set(key, CompareResult, compute)


def alternatives_result(session: Session, product: Product, by: str, limit: int) -> AlternativesResult:
    key = cache.make_key("alternatives", food_code=product.food_code, by=by, limit=limit)

    def compute() -> AlternativesResult:
        total, alternatives = find_alternatives(session, product, by, limit)
        return AlternativesResult(product=ProductItem.model_validate(product), by=by, total=total,
                                  items=[ProductItem.model_validate(p) for p in alternatives])

    return cache.get_or_set(key, AlternativesResult, compute)


# ---------------- JSON API ----------------

@app.get("/api/products", response_model=SearchResult)
def list_products(
    q: str = Query("", max_length=100, description="검색어"),
    target: SearchTarget = Query("name", description="검색어를 찾을 곳: name(제품 이름) / maker(회사 이름)"),
    category: str | None = Query(None, max_length=50, description="대표식품명 (예: 간장)"),
    basis: Basis | None = Query(None, description="기준량 100g / 100ml"),
    max_kcal: float | None = Query(None, ge=0, description="칼로리 이하 (기준량당 kcal)"),
    max_sodium: float | None = Query(None, ge=0, description="나트륨 이하 (기준량당 mg)"),
    max_sugar: float | None = Query(None, ge=0, description="당류 이하 (기준량당 g)"),
    max_sat_fat: float | None = Query(None, ge=0, description="포화지방 이하 (기준량당 g)"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> SearchResult:
    q = q.strip()
    if not q and not category:
        # 조건 없이 33만 건 전체를 정렬하는 요청은 받지 않는다
        raise HTTPException(status_code=400, detail="검색어나 대표식품명 중 하나는 입력해 주세요.")

    # 값을 넣은 상한 조건만 넘긴다
    limits = {"max_kcal": max_kcal, "max_sodium": max_sodium, "max_sugar": max_sugar, "max_sat_fat": max_sat_fat}
    max_values = {key: value for key, value in limits.items() if value is not None}

    return search_result(session, q, category, page, size, target, basis, max_values)


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

    return alternatives_result(session, product, by, limit)


@app.get("/api/compare", response_model=CompareResult)
def compare(
    category: str = Query(..., min_length=1, max_length=50, description="대표식품명 (예: 간장)"),
    basis: Basis = Query(..., description="기준량. 같은 기준량끼리만 비교한다"),
    sort: SortKey = Query("sodium", description="낮은 순으로 정렬할 영양값"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    session: Session = Depends(get_session),
) -> CompareResult:
    return compare_result(session, category, basis, sort, page, size)


# ---------------- 회원 API (v3) ----------------

# 'Authorization: Bearer <토큰>' 머리말을 읽는다. auto_error=False: 없을 때 403 대신 아래에서 401을 준다
bearer = HTTPBearer(auto_error=False)
LOGIN_FAILED = "이메일 또는 비밀번호가 맞지 않아요."  # 어느 쪽이 틀렸는지 알려 주지 않는다
LOGIN_AGAIN = "다시 로그인해 주세요."  # 리프레시 토큰이 없거나·끊겼거나·만료됐거나·재사용됨 (이유는 알려 주지 않는다)


def token_response(session: Session, user_id: int, refresh_token: str | None = None) -> TokenResponse:
    """액세스 토큰 + 리프레시 토큰 응답. 로그인이면 리프레시 토큰을 새 묶음으로 만들고, 순환이면 이미 만든 것을 넣는다."""
    return TokenResponse(
        access_token=auth.create_access_token(user_id),
        expires_in=auth.ACCESS_TOKEN_MINUTES * 60,
        refresh_token=refresh_token or refresh.issue(session, user_id),
        refresh_expires_in=refresh.REFRESH_TOKEN_DAYS * 24 * 60 * 60,
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    session: Session = Depends(get_session),
) -> User:
    """로그인이 필요한 API에 붙인다. 토큰이 없거나, 틀렸거나, 만료됐거나, 그 회원이 없으면 401."""
    user_id = auth.read_access_token(credentials.credentials) if credentials else None
    user = session.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="로그인이 필요해요.", headers={"WWW-Authenticate": "Bearer"})
    return user


@app.post("/api/auth/signup", response_model=UserItem, status_code=201)
def signup(body: SignupRequest, session: Session = Depends(get_session)) -> UserItem:
    user = User(email=body.email, password_hash=auth.hash_password(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:  # email unique: 이미 가입된 이메일 (동시에 두 번 가입해도 DB가 막아 준다)
        session.rollback()
        raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요.")
    session.refresh(user)  # DB가 정한 id·created_at을 읽어 온다
    return UserItem.model_validate(user)


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    email = auth.normalize_email(body.email)
    user = session.scalars(select(User).where(User.email == email)).one_or_none()

    # 가입하지 않은 이메일도 가짜 해시로 한 번 확인한다: 응답 시간이 같아서 가입 여부를 알 수 없게
    password_ok = auth.verify_password(body.password, user.password_hash if user else auth.DUMMY_HASH)
    if user is None or not password_ok:
        raise HTTPException(status_code=401, detail=LOGIN_FAILED)

    return token_response(session, user.id)


@app.post("/api/auth/refresh", response_model=TokenResponse)
def refresh_tokens(body: RefreshRequest, session: Session = Depends(get_session)) -> TokenResponse:
    """리프레시 토큰으로 새 액세스 토큰 + 새 리프레시 토큰을 받는다. 보낸 리프레시 토큰은 이제 못 쓴다."""
    rotated = refresh.rotate(session, body.refresh_token)
    if rotated is None:
        raise HTTPException(status_code=401, detail=LOGIN_AGAIN)
    user_id, new_refresh_token = rotated
    return token_response(session, user_id, new_refresh_token)


@app.post("/api/auth/logout", status_code=204)
def logout(body: RefreshRequest, session: Session = Depends(get_session)) -> Response:
    """이 기기의 로그인을 끊는다 (리프레시 토큰 묶음). 이미 받은 액세스 토큰은 15분 안에 만료된다.
    모르는 토큰이어도 204: 로그아웃은 몇 번 해도 결과가 같다."""
    refresh.logout(session, body.refresh_token)
    return Response(status_code=204)


@app.get("/api/me", response_model=UserItem)
def me(user: User = Depends(current_user)) -> UserItem:
    return UserItem.model_validate(user)


# ---------------- 화면 (HTML) ----------------
# API와 같은 함수(search_result, compare_result, alternatives_result)를 쓰고, 결과를 템플릿에 넘긴다.

SORT_LABELS = {"sodium": "나트륨", "sugar": "당류", "sat_fat": "포화지방"}

# 화면 검색어를 어디서 찾을지: 값 → 화면 이름
SCREEN_TARGETS = {"name": "제품 이름", "category": "대표식품명", "maker": "회사 이름"}

# 화면의 '상세 조건' 드래그바: (파라미터 이름, 화면 이름, 단위, 맨 오른쪽 값, 한 칸)
# 맨 오른쪽 값까지 끌어 두면 '제한 없음'이다 (기준량 100g·100ml당 값)
MAX_FIELDS = [
    ("max_kcal", "칼로리", "kcal", 900, 10),
    ("max_sodium", "나트륨", "mg", 8000, 100),
    ("max_sugar", "당류", "g", 100, 1),
    ("max_sat_fat", "포화지방", "g", 50, 0.5),
]
SLIDER_TOPS = {key: top for key, _, _, top, _ in MAX_FIELDS}


def parse_limit(text: str, top: float) -> float | None:
    """화면 폼의 상한 값. 비어 있거나 숫자가 아니거나 음수거나
    드래그바 맨 오른쪽(top) 이상이면 '조건 없음'(None)."""
    try:
        value = float(text)
    except ValueError:  # 빈칸("")도 여기로 온다
        return None
    return value if 0 <= value < top else None


@app.get("/", response_class=HTMLResponse)
def search_page(
    request: Request,
    q: str = Query("", max_length=100),
    # 검색어 칸은 하나이고, 어디서 찾을지만 고른다: 제품 이름 / 대표식품명 / 회사 이름
    target: str = Query("name"),
    basis: str = Query(""),
    # 폼에서 빈 칸은 빈 글자("")로 오므로 숫자가 아니라 글자로 받아 parse_limit으로 바꾼다
    max_kcal: str = Query("", max_length=20),
    max_sodium: str = Query("", max_length=20),
    max_sugar: str = Query("", max_length=20),
    max_sat_fat: str = Query("", max_length=20),
    page: int = Query(1, ge=1),
    size: int = Query(DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_session),
):
    q = q.strip()
    size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    target = target if target in SCREEN_TARGETS else "name"
    basis = basis if basis in ("100g", "100ml") else ""
    texts = {"max_kcal": max_kcal, "max_sodium": max_sodium, "max_sugar": max_sugar, "max_sat_fat": max_sat_fat}
    max_values = {key: parse_limit(text, SLIDER_TOPS[key]) for key, text in texts.items()}
    max_values = {key: value for key, value in max_values.items() if value is not None}

    result = None  # 검색어가 없으면 검색창만 보여준다
    if q:
        if target == "category":
            # 대표식품명은 정확히 같은 것만 (참치 → 참치김밥이 섞이지 않게)
            result = search_result(session, "", q, page, size, "name", basis or None, max_values)
        else:
            result = search_result(session, q, None, page, size, target, basis or None, max_values)

    # 지금 조건 그대로 쪽(과 쪽 크기)만 바꾼 주소 (비어 있는 조건은 주소에서 뺀다)
    params = {"q": q, "target": target, "basis": basis,
              **{key: f"{value:g}" for key, value in max_values.items()}}
    params = {key: value for key, value in params.items() if value}

    def page_url(n: int, page_size: int = size) -> str:
        return "/?" + urlencode({**params, "page": n, "size": page_size})

    return templates.TemplateResponse(
        request, "search.html",
        {"q": q, "target": target, "screen_targets": SCREEN_TARGETS, "basis": basis,
         "max_values": max_values, "max_fields": MAX_FIELDS,
         "result": result, "page_url": page_url, "page_sizes": PAGE_SIZES},
    )


@app.get("/products/{food_code}", response_class=HTMLResponse)
def detail_page(request: Request, food_code: str, session: Session = Depends(get_session)):
    product = session.get(Product, food_code)
    if product is None:
        return templates.TemplateResponse(request, "not_found.html", {}, status_code=404)

    alternatives = []
    for by, label, subject, note in [
        ("sodium", "나트륨", "나트륨이", ""),
        ("sugar", "당류", "당류가", " (나트륨이 이 제품보다 높은 제품은 뺐어요)"),
    ]:
        found = alternatives_result(session, product, by, ALTERNATIVES_ON_DETAIL)
        alternatives.append({
            "key": by,  # 표에서 강조할 칸
            "label": label,
            "subject": subject,  # 제목용 (조사가 달라서 따로 둔다)
            "note": note,
            "base_value": getattr(product, RECOMMEND_COLUMNS[by].key),  # None이면 '찾을 수 없음' 안내
            "total": found.total,
            # 'items'라고 하면 템플릿에서 딕셔너리의 .items() 메서드와 헷갈리므로 products로 둔다
            "products": found.items,
        })

    return templates.TemplateResponse(
        request, "detail.html",
        {"product": ProductItem.model_validate(product), "alternatives": alternatives},
    )


@app.get("/compare", response_class=HTMLResponse)
def compare_page(
    request: Request,
    category: str = Query(..., min_length=1, max_length=50),
    basis: Basis = Query(...),
    sort: SortKey = Query("sodium"),
    page: int = Query(1, ge=1),
    size: int = Query(DEFAULT_PAGE_SIZE),
    session: Session = Depends(get_session),
):
    size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    result = compare_result(session, category, basis, sort, page, size)

    def page_url(n: int, page_size: int = size) -> str:
        return "/compare?" + urlencode(
            {"category": category, "basis": basis, "sort": sort, "page": n, "size": page_size}
        )

    return templates.TemplateResponse(
        request, "compare.html",
        {"result": result, "sort_labels": SORT_LABELS, "page_url": page_url, "page_sizes": PAGE_SIZES},
    )
