"""로그인 실패 제한 테스트 (v3 3단계): 5번 틀리면 15분 잠금. 테스트 전용 Redis(TEST_REDIS_URL)를 쓴다."""

import pytest
import redis

from app import login_limit

EMAIL = "tester@example.com"
PASSWORD = "long-enough-password"


@pytest.fixture
def user(api):
    api.post("/api/auth/signup", json={"email": EMAIL, "password": PASSWORD})


def login(api, email=EMAIL, password=PASSWORD):
    return api.post("/api/auth/login", json={"email": email, "password": password})


def fail(api, times, email=EMAIL):
    for _ in range(times):
        assert login(api, email, "wrong-password").status_code == 401


def test_four_failures_then_correct_password_works_and_resets(api, user, login_limit_redis):
    fail(api, 4)

    assert login(api).status_code == 200
    # 성공하면 횟수가 지워져서, 다시 4번 틀려도 막히지 않는다
    fail(api, 4)
    assert login(api).status_code == 200


def test_fifth_failure_locks_even_correct_password(api, user, login_limit_redis):
    fail(api, 5)

    response = login(api)  # 맞는 비밀번호여도

    assert response.status_code == 429
    assert response.json() == {"detail": "로그인을 여러 번 실패했어요. 15분 뒤에 다시 해 주세요."}
    assert 0 < int(response.headers["Retry-After"]) <= 15 * 60


def test_lock_lasts_fifteen_minutes_from_last_failure(api, user, login_limit_redis):
    fail(api, 5)
    login(api)  # 막힌 동안의 시도는 세지 않고 시간을 늘리지도 않는다

    key = login_limit.key(EMAIL)
    assert login_limit_redis.get(key) == b"5"
    assert 0 < login_limit_redis.ttl(key) <= 15 * 60

    login_limit_redis.delete(key)  # 15분이 지나 키가 사라진 상황
    assert login(api).status_code == 200


def test_unknown_email_is_locked_the_same_way(api, user, login_limit_redis):
    fail(api, 5, email="nobody@example.com")
    fail(api, 5)

    unknown = login(api, email="nobody@example.com")
    known = login(api)

    # 막히는 모습이 같아서 가입 여부를 알 수 없다
    assert unknown.status_code == known.status_code == 429
    assert unknown.json() == known.json()


def test_lock_is_per_email_and_ignores_case(api, user, login_limit_redis):
    fail(api, 3)
    fail(api, 2, email="TESTER@Example.com")  # 대소문자만 다른 같은 이메일 → 합쳐서 5번

    assert login(api).status_code == 429
    assert login(api, email="other@example.com").status_code == 401  # 다른 이메일은 막히지 않음


def test_load_clears_cache_but_not_failures(api, user, login_limit_redis, monkeypatch):
    # 데이터 적재 후 캐시 비우기(nutri:*)가 실패 횟수(auth:login_fail:*)까지 지우면 안 된다
    from app import cache
    monkeypatch.setattr(cache, "client", login_limit_redis)
    fail(api, 5)

    cache.clear()

    assert login(api).status_code == 429


class BrokenRedis:
    """Redis가 꺼진 상황: 어떤 명령이든 바로 연결 오류. (실제로 꺼진 포트를 쓰면 요청마다 약 1초씩 기다려 느림)
    calls: Redis를 몇 번 불렀는지 (서킷 브레이커가 부르지 않고 건너뛰는지 확인용)"""

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        self.calls += 1
        raise redis.ConnectionError("Redis is down")


def test_login_is_refused_when_redis_is_down(api, user, monkeypatch):
    # Redis가 꺼져 실패 횟수를 확인할 수 없으면, 맞는 비밀번호여도 로그인을 받지 않는다 (보안 우선)
    monkeypatch.setattr(login_limit, "client", BrokenRedis())

    right = login(api)
    wrong = login(api, password="wrong-password")

    assert right.status_code == wrong.status_code == 503
    assert right.json() == {"detail": "지금은 로그인할 수 없어요. 잠시 뒤에 다시 해 주세요."}
    assert "access_token" not in right.json()


def test_failing_to_reset_after_success_still_logs_in(api, user, login_limit_redis, monkeypatch):
    # 확인·기록은 됐는데 성공 뒤 지우기만 실패한 경우: 비밀번호가 맞았으니 로그인은 된다
    def broken_delete(*args):
        raise redis.ConnectionError("Redis is down")

    monkeypatch.setattr(login_limit_redis, "delete", broken_delete)

    assert login(api).status_code == 200


def test_other_apis_work_when_redis_is_down(api, user, monkeypatch):
    # 실패 제한은 로그인에만 쓴다: 가입·토큰 순환은 Redis와 상관없이 동작
    monkeypatch.setattr(login_limit, "client", None)  # 토큰을 받는 동안만 정상
    tokens = login(api).json()
    monkeypatch.setattr(login_limit, "client", BrokenRedis())

    assert api.post("/api/auth/signup", json={"email": "new@example.com", "password": PASSWORD}).status_code == 201
    assert api.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}).status_code == 200


def test_after_redis_error_skips_redis_for_a_while(api, user, monkeypatch):
    # 서킷 브레이커: 한 번 오류가 나면 30초 동안은 Redis를 부르지 않고 바로 503 (요청마다 1초씩 기다리지 않게)
    broken = BrokenRedis()
    monkeypatch.setattr(login_limit, "client", broken)

    assert login(api).status_code == 503
    assert broken.calls == 1  # 첫 요청만 Redis를 불러 보고

    assert login(api).status_code == 503
    assert login(api, password="wrong-password").status_code == 503
    assert broken.calls == 1  # 다음 요청들은 부르지 않는다


def test_tries_redis_again_after_thirty_seconds(api, user, login_limit_redis, monkeypatch):
    monkeypatch.setattr(login_limit, "client", BrokenRedis())
    assert login(api).status_code == 503

    monkeypatch.setattr(login_limit, "client", login_limit_redis)  # Redis가 살아남
    assert login(api).status_code == 503  # 30초 안에는 아직 부르지 않음

    login_limit.down_until -= login_limit.DOWN_SECONDS  # 30초가 지난 상황
    assert login(api).status_code == 200  # 다시 불러 보고, 살아 있으니 정상
