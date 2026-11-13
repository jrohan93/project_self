"""회원 테스트 (v3 1단계): 가입, 로그인, 토큰으로 내 정보 보기."""

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import text

from app import auth

EMAIL = "tester@example.com"
PASSWORD = "long-enough-password"


def signup(api, email=EMAIL, password=PASSWORD):
    return api.post("/api/auth/signup", json={"email": email, "password": password})


def login(api, email=EMAIL, password=PASSWORD):
    return api.post("/api/auth/login", json={"email": email, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


# --- 비밀번호 해시 ---

def test_same_password_gives_different_hash_but_both_verify():
    first, second = auth.hash_password(PASSWORD), auth.hash_password(PASSWORD)

    assert first != second  # salt가 달라서 매번 다른 해시
    assert auth.verify_password(PASSWORD, first) and auth.verify_password(PASSWORD, second)
    assert not auth.verify_password("wrong-password", first)


def test_dummy_hash_matches_no_password():
    assert not auth.verify_password(PASSWORD, auth.DUMMY_HASH)


# --- 가입 ---

def test_signup_stores_lowercase_email_and_only_hash(engine, api):
    response = signup(api, email="  Tester@Example.COM ")

    assert response.status_code == 201
    assert response.json()["email"] == EMAIL
    assert "password" not in str(response.json())  # 응답에 비밀번호·해시가 없다

    with engine.connect() as conn:
        stored = conn.execute(text("SELECT password_hash FROM users")).scalar_one()
    assert stored != PASSWORD and stored.startswith("$2b$")


def test_same_email_cannot_sign_up_twice(api):
    signup(api)

    response = signup(api, email="TESTER@example.com")  # 대소문자만 다른 같은 이메일

    assert response.status_code == 409


@pytest.mark.parametrize("email, password", [
    ("not-an-email", PASSWORD),
    ("a@b", PASSWORD),          # 점이 없음
    (EMAIL, "Ab1!"),           # 4종류지만 8자 미만
    (EMAIL, "가" * 23 + "ab12"),  # 2종류·27자로 조합은 맞지만 69+4 = 73바이트 (bcrypt 72바이트 넘음)
])
def test_signup_rejects_bad_input(api, email, password):
    assert signup(api, email, password).status_code == 422


@pytest.mark.parametrize("password", [
    "abcdefghijkl",   # 1종류(소문자)는 길어도 안 됨
    "12345678901",    # 1종류(숫자)
    "abcd12345",      # 2종류인데 9자 (10자 필요)
    "abc123!",        # 3종류인데 7자 (8자 필요)
    "가나다라마바사아자차",  # 한글은 종류로 세지 않음
])
def test_signup_rejects_password_breaking_combination_rule(api, password):
    response = signup(api, password=password)

    assert response.status_code == 422
    assert "2종류 이상이면 10자 이상" in response.text  # 어떤 규칙인지 알려 준다


@pytest.mark.parametrize("password", [
    "abcde12345",     # 2종류(소문자·숫자) 10자
    "abcd123!",       # 3종류(소문자·숫자·특수) 8자
    "Abcd1234",       # 3종류(대문자·소문자·숫자) 8자
])
def test_signup_accepts_password_following_combination_rule(api, password):
    assert signup(api, password=password).status_code == 201


def test_password_kinds():
    assert auth.password_kinds("abc") == 1
    assert auth.password_kinds("Abc1!") == 4
    assert auth.password_kinds("가나다") == 0


def test_korean_password_within_72_bytes_works(api):
    password = "가" * 22 + "ab12xy"  # 한글 66바이트 + 6바이트 = 72바이트, 2종류·28자
    signup(api, password=password)

    assert login(api, password=password).status_code == 200


# --- 로그인 ---

def test_login_gives_token_that_opens_me(api):
    signup(api)

    response = login(api, email="TESTER@EXAMPLE.COM")  # 로그인도 대소문자 상관없이

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 15 * 60

    me = api.get("/api/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


def test_wrong_password_and_unknown_email_look_the_same(api):
    signup(api)

    wrong_password = login(api, password="wrong-password")
    unknown_email = login(api, email="nobody@example.com")

    # 가입 여부를 알 수 없게 상태 코드와 문구가 똑같다
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


# --- 토큰 ---

def test_me_without_token_is_401(api):
    response = api.get("/api/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_rejects_broken_expired_and_forged_tokens(api, monkeypatch):
    signup(api)
    user_id = api.get("/api/me", headers=bearer(login(api).json()["access_token"])).json()["id"]

    # 만료된 토큰
    monkeypatch.setattr(auth, "ACCESS_TOKEN_MINUTES", -1)
    expired = auth.create_access_token(user_id)
    # 다른 키로 서명한 토큰 (서버 키를 모르는 사람이 만든 것)
    forged = jwt.encode({"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(minutes=5)},
                        "someone-elses-secret-0123456789abcdef", algorithm="HS256")

    for token in ["garbage", expired, forged]:
        assert api.get("/api/me", headers=bearer(token)).status_code == 401


def test_token_of_deleted_user_is_401(engine, api):
    signup(api)
    token = login(api).json()["access_token"]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users"))

    assert api.get("/api/me", headers=bearer(token)).status_code == 401
