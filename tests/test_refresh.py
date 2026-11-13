"""리프레시 토큰 테스트 (v3 2단계): 순환, 재사용 감지, 만료, 로그아웃."""

import pytest
from sqlalchemy import text

from app import refresh

EMAIL = "tester@example.com"
PASSWORD = "long-enough-password"


@pytest.fixture
def user(api):
    api.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})


def login(api):
    return api.post("/api/auth/login", json={"email": EMAIL, "password": PASSWORD}).json()


def use(api, refresh_token):
    return api.post("/api/auth/refresh", json={"refresh_token": refresh_token})


def me(api, access_token):
    return api.get("/api/me", headers={"Authorization": f"Bearer {access_token}"})


def test_login_gives_refresh_token_and_db_keeps_only_hash(engine, api, user):
    tokens = login(api)

    assert tokens["refresh_expires_in"] == 14 * 24 * 60 * 60
    with engine.connect() as conn:
        stored = conn.execute(text("SELECT token_hash FROM refresh_tokens")).scalar_one()
    assert stored != tokens["refresh_token"]  # 원문이 아니라
    assert stored == refresh.hash_token(tokens["refresh_token"])  # 해시만 저장


def test_refresh_gives_new_working_tokens(api, user):
    old = login(api)

    response = use(api, old["refresh_token"])

    assert response.status_code == 200
    new = response.json()
    assert new["refresh_token"] != old["refresh_token"]  # 순환: 새 리프레시 토큰
    assert me(api, new["access_token"]).json()["email"] == EMAIL
    assert use(api, new["refresh_token"]).status_code == 200  # 새 토큰으로 또 순환할 수 있다


def test_reusing_old_refresh_token_revokes_all_tokens_of_user(api, user):
    first = login(api)
    other_device = login(api)  # 다른 기기에서 한 로그인
    second = use(api, first["refresh_token"]).json()

    # 이미 쓴 first 토큰이 다시 옴 (도둑이 훔쳐 간 옛 토큰이라고 본다)
    assert use(api, first["refresh_token"]).status_code == 401

    # 진짜 주인 쪽 최신 토큰도, 다른 기기 토큰도 모두 끊긴다 → 다시 로그인해야 함
    assert use(api, second["refresh_token"]).status_code == 401
    assert use(api, other_device["refresh_token"]).status_code == 401
    # 다시 로그인하면 정상
    assert use(api, login(api)["refresh_token"]).status_code == 200


def test_unknown_and_expired_refresh_tokens_are_401(api, user, monkeypatch):
    assert use(api, "made-up-token").status_code == 401

    monkeypatch.setattr(refresh, "REFRESH_TOKEN_DAYS", -1)  # 만들자마자 만료된 토큰
    expired = login(api)["refresh_token"]
    assert use(api, expired).status_code == 401


def test_401_message_does_not_tell_why(api, user, monkeypatch):
    tokens = login(api)
    use(api, tokens["refresh_token"])

    reused = use(api, tokens["refresh_token"]).json()
    unknown = use(api, "made-up-token").json()

    assert reused == unknown == {"detail": "다시 로그인해 주세요."}


def test_logout_revokes_only_this_device(api, user):
    this_device = login(api)
    other_device = login(api)
    rotated = use(api, this_device["refresh_token"]).json()  # 이 기기에서 한 번 순환한 뒤

    assert api.post("/api/auth/logout", json={"refresh_token": rotated["refresh_token"]}).status_code == 204

    assert use(api, rotated["refresh_token"]).status_code == 401
    assert use(api, other_device["refresh_token"]).status_code == 200  # 다른 기기는 그대로


def test_logout_with_unknown_token_is_still_204(api):
    assert api.post("/api/auth/logout", json={"refresh_token": "made-up-token"}).status_code == 204


def test_reuse_after_logout_is_just_401(api, user):
    # 로그아웃한 토큰이 다시 와도(끊긴 토큰) 다른 기기까지 끊지는 않는다
    tokens = login(api)
    other_device = login(api)
    api.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})

    assert use(api, tokens["refresh_token"]).status_code == 401
    assert use(api, other_device["refresh_token"]).status_code == 200


def test_deleting_user_deletes_refresh_tokens(engine, api, user):
    login(api)
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users"))
        left = conn.execute(text("SELECT COUNT(*) FROM refresh_tokens")).scalar_one()

    assert left == 0  # 외래 키 ON DELETE CASCADE


def test_two_requests_with_same_token_at_once_only_one_wins(engine, api, user, monkeypatch):
    # 동시에 온 두 요청을 흉내 낸다: 이 요청이 토큰을 읽은 '바로 뒤'에 다른 요청이 먼저 순환에 써 버린 상황
    tokens = login(api)
    original_find = refresh.find

    def find_then_other_request_wins(session, raw):
        token = original_find(session, raw)  # 이 요청이 읽을 때는 아직 안 쓴 토큰
        with engine.begin() as conn:
            conn.execute(text("UPDATE refresh_tokens SET used_at = UTC_TIMESTAMP()"))
        return token

    monkeypatch.setattr(refresh, "find", find_then_other_request_wins)

    # 읽은 값만 보면 '안 쓴 토큰'이지만, 조건부 UPDATE가 0행이라 재사용으로 처리된다
    assert use(api, tokens["refresh_token"]).status_code == 401
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM refresh_tokens WHERE revoked_at IS NULL")).scalar_one() == 0
