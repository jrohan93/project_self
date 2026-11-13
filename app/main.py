"""FastAPI 앱. 실행: uvicorn app.main:app --reload

/api/... 는 JSON API, 나머지(/, /products/..., /compare, /login, /favorites ...)는 Jinja2로 만든 HTML 화면.
API는 'Authorization: Bearer 토큰'으로, 화면은 HttpOnly 쿠키로 로그인을 확인한다.
"""

import os
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple
from urllib.parse import urlencode

import redis
from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.templating import Jinja2Templates
from markupsafe import Markup
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import auth, cache, favorites, login_limit, refresh
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
LOGIN_LOCKED = "로그인을 여러 번 실패했어요. 15분 뒤에 다시 해 주세요."
LOGIN_UNAVAILABLE = "지금은 로그인할 수 없어요. 잠시 뒤에 다시 해 주세요."  # Redis가 꺼져 실패 횟수를 확인할 수 없을 때
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


def create_user(session: Session, body: SignupRequest) -> User:
    """회원가입 (API·화면 공용). 이미 가입된 이메일이면 409."""
    user = User(email=body.email, password_hash=auth.hash_password(body.password))
    session.add(user)
    try:
        session.commit()
    except IntegrityError:  # email unique: 이미 가입된 이메일 (동시에 두 번 가입해도 DB가 막아 준다)
        session.rollback()
        raise HTTPException(status_code=409, detail="이미 가입된 이메일이에요.")
    session.refresh(user)  # DB가 정한 id·created_at을 읽어 온다
    return user


@app.post("/api/auth/signup", response_model=UserItem, status_code=201)
def signup(body: SignupRequest, session: Session = Depends(get_session)) -> UserItem:
    return UserItem.model_validate(create_user(session, body))


def authenticate(session: Session, email: str, password: str) -> User:
    """이메일·비밀번호 확인 (API·화면 공용). 실패하면 401, 5번 실패로 막혀 있으면 429, Redis가 꺼져 있으면 503."""
    email = auth.normalize_email(email)

    try:
        # 5번 틀려서 막혀 있으면 비밀번호를 확인하지도 않는다 (맞는 비밀번호여도 막는다: 아니면 계속 넣어 볼 수 있음)
        wait = login_limit.locked_seconds(email)
        if wait:
            raise HTTPException(status_code=429, detail=LOGIN_LOCKED, headers={"Retry-After": str(wait)})

        user = session.scalars(select(User).where(User.email == email)).one_or_none()

        # 가입하지 않은 이메일도 가짜 해시로 한 번 확인한다: 응답 시간이 같아서 가입 여부를 알 수 없게
        password_ok = auth.verify_password(password, user.password_hash if user else auth.DUMMY_HASH)
        if user is None or not password_ok:
            login_limit.record_failure(email)  # 가입하지 않은 이메일도 똑같이 센다
            raise HTTPException(status_code=401, detail=LOGIN_FAILED)
    except redis.RedisError:
        # Redis가 꺼져 실패 횟수를 확인·기록할 수 없으면 로그인을 받지 않는다 (제한 없이 받으면 무차별 대입을 못 막음)
        raise HTTPException(status_code=503, detail=LOGIN_UNAVAILABLE) from None

    login_limit.reset(email)  # 지우지 못해도 로그인은 그대로 (login_limit.reset 참고)
    return user


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, session: Session = Depends(get_session)) -> TokenResponse:
    user = authenticate(session, body.email, body.password)
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


# ---------------- 관심 제품 API (v3 4단계) ----------------
# 주소에 회원 id를 넣지 않는다(/api/me/...): 누구의 목록인지는 토큰으로만 정해져서 남의 목록을 고를 방법이 없다

@app.get("/api/me/favorites", response_model=list[ProductItem])
def list_favorites(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[ProductItem]:
    """내 관심 제품, 최근에 저장한 것 먼저."""
    return [ProductItem.model_validate(p) for p in favorites.list_products(session, user.id)]


@app.put("/api/me/favorites/{food_code}", status_code=204)
def add_favorite(food_code: str, user: User = Depends(current_user),
                 session: Session = Depends(get_session)) -> Response:
    """저장. PUT: 몇 번 해도 결과가 같다 (이미 저장했어도 204). 없는 제품이면 404."""
    if not favorites.add(session, user.id, food_code):
        raise HTTPException(status_code=404, detail="해당 제품이 없어요.")
    return Response(status_code=204)


@app.delete("/api/me/favorites/{food_code}", status_code=204)
def remove_favorite(food_code: str, user: User = Depends(current_user),
                    session: Session = Depends(get_session)) -> Response:
    """내 목록에서 지운다. 내 목록에 없으면 404 (다른 회원이 저장한 제품이어도 똑같이 404)."""
    if not favorites.remove(session, user.id, food_code):
        raise HTTPException(status_code=404, detail="관심 제품에 없는 제품이에요.")
    return Response(status_code=204)


# ---------------- 화면 (HTML) ----------------
# API와 같은 함수(search_result, compare_result, alternatives_result)를 쓰고, 결과를 템플릿에 넘긴다.

# ----- 화면 로그인 (v3 4단계): 토큰을 HttpOnly 쿠키에 둔다 -----
# - HttpOnly: 자바스크립트가 쿠키를 읽을 수 없다 → 화면에 XSS가 생겨도 토큰을 훔쳐 가지 못한다
# - SameSite=Lax: 다른 사이트에서 보낸 POST에는 쿠키가 붙지 않는다 → 남의 사이트가 몰래 관심 제품을 바꾸지 못한다(CSRF).
#   그래서 상태를 바꾸는 화면 요청(로그인·로그아웃·관심 제품 추가·빼기)은 모두 POST 폼으로만 받는다
# - API(/api/...)는 쿠키를 보지 않고 Bearer 토큰만 본다: API는 CSRF 걱정이 없다
ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
COOKIE_SECURE = os.getenv("COOKIE_SECURE") == "1"  # 운영(HTTPS)에서는 1: HTTPS로만 쿠키를 보낸다


class ScreenLogin(NamedTuple):
    user: User | None  # 로그인한 회원 (안 했으면 None)
    new_tokens: TokenResponse | None  # 액세스 토큰이 만료돼 리프레시 토큰으로 새로 받았으면 그 토큰 (쿠키를 바꿔야 함)
    expired: bool  # 리프레시 토큰도 못 쓰게 됐으면 True (쿠키를 지워야 함)


def screen_login(request: Request, session: Session = Depends(get_session)) -> ScreenLogin:
    """화면 요청에서 로그인한 회원을 찾는다. 로그인하지 않아도 화면은 볼 수 있으니 오류를 내지 않는다.

    1. 액세스 토큰 쿠키가 맞으면 그 회원
    2. 없거나 만료됐으면 리프레시 토큰 쿠키로 순환해서 새 토큰을 받는다 (API의 /api/auth/refresh와 같은 일)
    """
    user_id = auth.read_access_token(request.cookies.get(ACCESS_COOKIE, ""))
    if user_id is not None:
        return ScreenLogin(session.get(User, user_id), None, False)

    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if not raw_refresh:
        return ScreenLogin(None, None, False)
    rotated = refresh.rotate(session, raw_refresh)
    if rotated is None:  # 만료·로그아웃·재사용: 다시 로그인해야 한다
        return ScreenLogin(None, None, True)
    user_id, new_refresh_token = rotated
    return ScreenLogin(session.get(User, user_id), token_response(session, user_id, new_refresh_token), False)


def set_login_cookies(response: Response, tokens: TokenResponse) -> None:
    for name, value, seconds in [(ACCESS_COOKIE, tokens.access_token, tokens.expires_in),
                                 (REFRESH_COOKIE, tokens.refresh_token, tokens.refresh_expires_in)]:
        response.set_cookie(name, value, max_age=seconds, httponly=True, samesite="lax", secure=COOKIE_SECURE)


def clear_login_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    response.delete_cookie(REFRESH_COOKIE, httponly=True, samesite="lax", secure=COOKIE_SECURE)


def apply_login_cookies(response: Response, login: ScreenLogin) -> Response:
    """screen_login에서 토큰이 바뀌었거나 끊겼으면 응답 쿠키에 반영한다."""
    if login.new_tokens:
        set_login_cookies(response, login.new_tokens)
    elif login.expired:
        clear_login_cookies(response)
    return response


def render(request: Request, login: ScreenLogin, name: str, context: dict, status_code: int = 200) -> Response:
    """화면을 그린다. 모든 화면 머리에 로그인 상태가 보이도록 user를 같이 넘긴다."""
    response = templates.TemplateResponse(request, name, {**context, "user": login.user}, status_code=status_code)
    return apply_login_cookies(response, login)


def safe_next(next_url: str) -> str:
    """로그인 뒤 돌아갈 주소. 우리 사이트 안의 주소(/로 시작)만 받는다.
    //evil.com 이나 /\\evil.com 같은 주소는 브라우저가 다른 사이트로 보내므로 막는다 (열린 리다이렉트 방지)."""
    if next_url.startswith("/") and not next_url.startswith("//") and "\\" not in next_url:
        return next_url
    return "/"


def go(url: str) -> RedirectResponse:
    # 303: POST 폼을 처리한 뒤 GET으로 다른 화면을 보여준다 (새로 고침해도 폼이 다시 전송되지 않게)
    return RedirectResponse(url, status_code=303)


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
    login: ScreenLogin = Depends(screen_login),
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

    return render(
        request, login, "search.html",
        {"q": q, "target": target, "screen_targets": SCREEN_TARGETS, "basis": basis,
         "max_values": max_values, "max_fields": MAX_FIELDS,
         "result": result, "page_url": page_url, "page_sizes": PAGE_SIZES},
    )


@app.get("/products/{food_code}", response_class=HTMLResponse)
def detail_page(request: Request, food_code: str, session: Session = Depends(get_session),
                login: ScreenLogin = Depends(screen_login)):
    product = session.get(Product, food_code)
    if product is None:
        return render(request, login, "not_found.html", {}, status_code=404)

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

    saved = login.user is not None and favorites.is_saved(session, login.user.id, food_code)
    return render(
        request, login, "detail.html",
        {"product": ProductItem.model_validate(product), "alternatives": alternatives, "saved": saved},
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
    login: ScreenLogin = Depends(screen_login),
):
    size = size if size in PAGE_SIZES else DEFAULT_PAGE_SIZE
    result = compare_result(session, category, basis, sort, page, size)

    def page_url(n: int, page_size: int = size) -> str:
        return "/compare?" + urlencode(
            {"category": category, "basis": basis, "sort": sort, "page": n, "size": page_size}
        )

    return render(
        request, login, "compare.html",
        {"result": result, "sort_labels": SORT_LABELS, "page_url": page_url, "page_sizes": PAGE_SIZES},
    )


# ----- 회원 화면 (v3 4단계) -----

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = Query("/", max_length=500),
               login: ScreenLogin = Depends(screen_login)):
    if login.user:  # 이미 로그인했으면 폼을 보여줄 필요가 없다
        return apply_login_cookies(go(safe_next(next)), login)
    return render(request, login, "login.html", {"next": safe_next(next), "email": "", "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form("", max_length=255), password: str = Form("", max_length=200),
                 next: str = Form("/", max_length=500), session: Session = Depends(get_session)):
    """API 로그인과 같은 authenticate를 쓴다: 실패 제한·같은 실패 문구·Redis 고장 시 거절이 그대로 적용된다."""
    try:
        user = authenticate(session, email, password)
    except HTTPException as error:
        context = {"next": safe_next(next), "email": email, "error": error.detail, "user": None}
        return templates.TemplateResponse(request, "login.html", context,
                                          status_code=error.status_code, headers=error.headers)
    response = go(safe_next(next))
    set_login_cookies(response, token_response(session, user.id))
    return response


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request, next: str = Query("/", max_length=500),
                login: ScreenLogin = Depends(screen_login)):
    if login.user:
        return apply_login_cookies(go(safe_next(next)), login)
    return render(request, login, "signup.html",
                  {"next": safe_next(next), "email": "", "error": None, "rule": auth.PASSWORD_RULE})


@app.post("/signup", response_class=HTMLResponse)
def signup_submit(request: Request, email: str = Form("", max_length=255), password: str = Form("", max_length=200),
                  next: str = Form("/", max_length=500), session: Session = Depends(get_session)):
    """API 가입과 같은 검사(SignupRequest)와 같은 create_user를 쓴다. 가입하면 바로 로그인된다."""
    try:
        user = create_user(session, SignupRequest(email=email, password=password))
    except ValidationError as error:
        first = error.errors()[0]
        # 우리가 만든 검사(이메일 형식·비밀번호 규칙)는 그 문구를, 나머지(너무 김 등)는 짧은 안내를 보여준다
        message = str(first["ctx"]["error"]) if "error" in first.get("ctx", {}) else "입력한 값을 확인해 주세요."
        return signup_error(request, next, email, message, 422)
    except HTTPException as error:  # 이미 가입된 이메일
        return signup_error(request, next, email, error.detail, error.status_code)
    response = go(safe_next(next))
    set_login_cookies(response, token_response(session, user.id))
    return response


def signup_error(request: Request, next: str, email: str, message: str, status_code: int) -> Response:
    context = {"next": safe_next(next), "email": email, "error": message, "rule": auth.PASSWORD_RULE, "user": None}
    return templates.TemplateResponse(request, "signup.html", context, status_code=status_code)


@app.post("/logout")
def logout_submit(request: Request, session: Session = Depends(get_session)):
    """이 브라우저의 로그인만 끊는다 (API 로그아웃과 같은 refresh.logout)."""
    raw_refresh = request.cookies.get(REFRESH_COOKIE)
    if raw_refresh:
        refresh.logout(session, raw_refresh)
    response = go("/")
    clear_login_cookies(response)
    return response


@app.get("/favorites", response_class=HTMLResponse)
def favorites_page(request: Request, session: Session = Depends(get_session),
                   login: ScreenLogin = Depends(screen_login)):
    if login.user is None:
        return apply_login_cookies(go("/login?next=/favorites"), login)
    products = [ProductItem.model_validate(p) for p in favorites.list_products(session, login.user.id)]
    return render(request, login, "favorites.html", {"products": products})


@app.post("/favorites/{food_code}")
def favorite_add_submit(food_code: str, request: Request, session: Session = Depends(get_session),
                        login: ScreenLogin = Depends(screen_login)):
    if login.user is None:
        return apply_login_cookies(go(f"/login?next=/products/{food_code}"), login)
    if not favorites.add(session, login.user.id, food_code):
        return render(request, login, "not_found.html", {}, status_code=404)
    return apply_login_cookies(go(f"/products/{food_code}"), login)


@app.post("/favorites/{food_code}/delete")
def favorite_remove_submit(food_code: str, request: Request, next: str = Form("/favorites", max_length=500),
                           session: Session = Depends(get_session), login: ScreenLogin = Depends(screen_login)):
    if login.user is None:
        return apply_login_cookies(go("/login?next=/favorites"), login)
    if not favorites.remove(session, login.user.id, food_code):  # 내 목록에 없음 (남의 것이어도 같음)
        return render(request, login, "not_found.html",
                      {"message": "관심 제품에 없는 제품이에요."}, status_code=404)
    return apply_login_cookies(go(safe_next(next)), login)

