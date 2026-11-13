"""회원 화면 테스트 (v3 4단계): 쿠키 로그인, 가입, 로그아웃, 관심 제품 화면.

TestClient는 브라우저처럼 받은 쿠키를 저장해 두고 다음 요청에 붙인다.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import auth
from app.loader import save
from app.main import app

EMAIL = "me@example.com"
PASSWORD = "long-enough-password"


def product(code, name):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": "간장", "basis": "100ml",
            "energy_kcal": 60, "sodium_mg": 6000, "sugar_g": 1, "sat_fat_g": 0}


@pytest.fixture
def browser(engine, api):
    save(engine, [product("P1", "양조간장"), product("P2", "저염간장")])
    api.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})
    return api


def log_in(browser, next_url="/"):
    return browser.post("/login", data={"email": EMAIL, "password": PASSWORD, "next": next_url},
                        follow_redirects=False)


def break_access_cookie(browser):
    """15분이 지나 액세스 토큰을 못 쓰게 된 상황. 서버가 준 쿠키와 같은 도메인으로 덮어써야 하나로 남는다."""
    browser.cookies.set("access_token", "expired-or-broken", domain="testserver.local")


# --- 로그인 없이 ---

def test_search_and_detail_work_without_login(browser):
    assert browser.get("/?q=간장").status_code == 200
    html = browser.get("/products/P1").text

    assert "로그인하면 관심 제품에 저장할 수 있어요" in html
    assert 'href="/login?next=/products/P1"' in html


def test_favorites_page_sends_to_login(browser):
    response = browser.get("/favorites", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=/favorites"


def test_saving_without_login_sends_to_login(browser):
    response = browser.post("/favorites/P1", follow_redirects=False)

    assert response.headers["location"] == "/login?next=/products/P1"


# --- 로그인 ---

def test_login_sets_httponly_cookies_and_goes_back(browser):
    response = log_in(browser, "/products/P1")

    assert response.status_code == 303
    assert response.headers["location"] == "/products/P1"
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2  # 액세스 토큰, 리프레시 토큰
    for cookie in cookies:
        assert "HttpOnly" in cookie  # 자바스크립트가 읽을 수 없게
        assert "SameSite=lax" in cookie  # 다른 사이트의 POST에는 붙지 않게
    assert EMAIL in browser.get("/").text  # 머리에 로그인 상태


def test_wrong_password_shows_same_message(browser):
    response = browser.post("/login", data={"email": EMAIL, "password": "wrong-password"})

    assert response.status_code == 401
    assert "이메일 또는 비밀번호가 맞지 않아요." in response.text
    assert "access_token" not in browser.cookies


def test_screen_login_uses_failure_limit(browser, login_limit_redis):
    for _ in range(5):
        browser.post("/login", data={"email": EMAIL, "password": "wrong-password"})

    response = browser.post("/login", data={"email": EMAIL, "password": PASSWORD})  # 맞는 비밀번호여도

    assert response.status_code == 429
    assert "15분 뒤에 다시" in response.text


@pytest.mark.parametrize("next_url", ["https://evil.example", "//evil.example", "/\\evil.example"])
def test_next_must_stay_on_this_site(browser, next_url):
    # 로그인 뒤 다른 사이트로 보내는 주소는 받지 않는다 (열린 리다이렉트 방지)
    assert log_in(browser, next_url).headers["location"] == "/"


def test_logout_clears_cookies_and_revokes_refresh_token(engine, browser):
    log_in(browser)

    response = browser.post("/logout", follow_redirects=False)

    assert response.headers["location"] == "/"
    assert "access_token" not in browser.cookies
    assert "로그인" in browser.get("/").text
    with engine.connect() as conn:  # 서버에서도 그 리프레시 토큰이 끊김
        assert conn.execute(text("SELECT COUNT(*) FROM refresh_tokens WHERE revoked_at IS NULL")).scalar_one() == 0


def test_expired_access_cookie_is_renewed_with_refresh_cookie(browser):
    log_in(browser)
    old_refresh = browser.cookies["refresh_token"]
    break_access_cookie(browser)

    html = browser.get("/").text

    assert EMAIL in html  # 여전히 로그인 상태
    assert browser.cookies["refresh_token"] != old_refresh  # 리프레시 토큰이 순환됨
    assert auth.read_access_token(browser.cookies["access_token"]) is not None  # 새 액세스 토큰


def test_revoked_refresh_cookie_logs_out_and_clears_cookies(engine, browser):
    log_in(browser)
    break_access_cookie(browser)
    with engine.begin() as conn:
        conn.execute(text("UPDATE refresh_tokens SET revoked_at = UTC_TIMESTAMP()"))  # 다른 곳에서 끊김

    html = browser.get("/").text

    assert EMAIL not in html
    assert "refresh_token" not in browser.cookies


# --- 회원가입 ---

def test_signup_logs_in_right_away(api):
    response = api.post("/signup", data={"email": "New@Example.com", "password": PASSWORD, "next": "/favorites"},
                        follow_redirects=False)

    assert response.headers["location"] == "/favorites"
    assert "new@example.com" in api.get("/").text  # 소문자로 저장되고 바로 로그인


def test_signup_shows_rule_message_and_keeps_email(api):
    response = api.post("/signup", data={"email": "new@example.com", "password": "short"})

    assert response.status_code == 422
    assert "2종류 이상이면 10자 이상" in response.text  # 비밀번호 규칙 문구 (API와 같은 검사)
    assert 'value="new@example.com"' in response.text  # 다시 입력하지 않게


def test_signup_duplicate_email(browser):
    response = browser.post("/signup", data={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 409
    assert "이미 가입된 이메일이에요." in response.text


# --- 관심 제품 ---

def test_save_from_detail_then_list_then_remove(browser):
    log_in(browser)

    html = browser.post("/favorites/P1").text  # 저장하면 상세 화면으로 돌아온다
    assert "관심 제품에서 빼기" in html

    browser.post("/favorites/P2")
    html = browser.get("/favorites").text
    assert html.index("저염간장") < html.index("양조간장")  # 최근에 저장한 것 먼저
    assert "2개" in html

    html = browser.post("/favorites/P1/delete", data={"next": "/favorites"}).text
    assert "양조간장" not in html
    assert "저염간장" in html


def test_empty_favorites_page(browser):
    log_in(browser)

    assert "아직 저장한 제품이 없어요" in browser.get("/favorites").text


def test_removing_others_favorite_is_404(browser):
    other = TestClient(app)
    other.post("/signup", data={"email": "other@example.com", "password": PASSWORD})
    other.post("/favorites/P1")
    log_in(browser)

    response = browser.post("/favorites/P1/delete")

    assert response.status_code == 404
    assert "관심 제품에 없는 제품이에요." in response.text
    assert "양조간장" in other.get("/favorites").text  # 그 회원의 데이터는 그대로


def test_saving_unknown_product_is_404(browser):
    log_in(browser)

    assert browser.post("/favorites/NO-SUCH").status_code == 404
