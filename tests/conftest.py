"""여러 테스트 파일이 같이 쓰는 준비물.

engine: 테스트 전용 DB(TEST_DATABASE_URL)에 빈 products·users·refresh_tokens 테이블을 만들어 준다.
        마이그레이션은 테스트 실행마다 한 번만 처음부터 다시 적용하고(FULLTEXT 인덱스 만들기가 느려서),
        테스트마다 DELETE로 테이블만 비운다.
api: 그 테스트 DB를 쓰는 FastAPI TestClient.
redis_cache: 테스트 전용 Redis(TEST_REDIS_URL)를 비워서 캐시로 끼운다. 이게 없는 테스트는 캐시를 끈 채로 돈다.
login_limit_redis: 같은 방식으로 로그인 실패 제한(v3 3단계)에 끼운다. 이게 없으면 제한 없이 돈다.
MySQL이 떠 있지 않으면 그 테스트는 건너뛴다 (docker compose up -d 후 실행).
"""

import os

import bcrypt
import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app import auth, cache, login_limit
from app.main import app, get_session

load_dotenv()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")


@pytest.fixture(autouse=True)
def no_cache(monkeypatch):
    """모든 테스트에서 기본은 캐시·로그인 실패 제한 끔: 실제 캐시(REDIS_URL)에 테스트 데이터가 섞이지 않게,
    그리고 테스트마다 테이블을 비우는데 앞 테스트의 캐시 결과가 나오지 않게."""
    monkeypatch.setattr(cache, "client", None)
    monkeypatch.setattr(login_limit, "client", None)  # 로그인 실패 제한도 기본은 끔 (같은 이유)
    monkeypatch.setattr(login_limit, "down_until", 0.0)  # 앞 테스트의 "Redis 꺼짐" 표시가 넘어오지 않게


# 반복 2^4로 만든 가짜 해시 (auth.DUMMY_HASH는 2^12라 한 번에 0.3초)
FAST_DUMMY_HASH = bcrypt.hashpw(b"no-such-user", bcrypt.gensalt(4)).decode()


@pytest.fixture(autouse=True)
def fast_auth(monkeypatch):
    """회원 테스트: bcrypt 반복을 2^12 → 2^4로 줄여 빠르게(해시 한 번 약 0.3초 → 1ms),
    토큰 서명 키는 .env 값 대신 테스트용 값을 쓴다."""
    monkeypatch.setattr(auth, "BCRYPT_ROUNDS", 4)
    monkeypatch.setattr(auth, "DUMMY_HASH", FAST_DUMMY_HASH)  # 없는 이메일 확인도 빠르게
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-pytest-only-0123456789")


@pytest.fixture(scope="session")
def migrated_engine():
    """테스트 실행 전체에서 한 번: 마이그레이션을 처음부터 다시 적용한다."""
    if not TEST_DATABASE_URL:
        pytest.skip(".env에 TEST_DATABASE_URL이 없음")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("테스트 DB에 연결할 수 없음 (docker compose up -d 했는지 확인)")

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    yield engine
    engine.dispose()


@pytest.fixture
def engine(migrated_engine):
    """테스트마다: 테이블을 비워서 빈 테이블로 시작한다 (인덱스는 그대로).

    TRUNCATE가 아니라 DELETE: TRUNCATE는 테이블을 새로 만들면서 FULLTEXT 보조 테이블까지
    다시 만들어 한 번에 1~2초 걸린다. 테스트 테이블은 몇 행뿐이라 DELETE는 거의 0초.
    """
    with migrated_engine.begin() as conn:
        conn.execute(text("DELETE FROM products"))
        conn.execute(text("DELETE FROM users"))  # refresh_tokens는 외래 키 CASCADE로 같이 지워진다
    return migrated_engine


@pytest.fixture
def api(engine):
    # 앱이 실제 DB 대신 테스트 DB를 쓰도록 세션을 바꿔 끼운다
    TestSession = sessionmaker(engine)

    def test_session():
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def redis_cache(monkeypatch):
    """테스트 전용 Redis DB를 비우고 캐시로 끼운다. Redis가 꺼져 있으면 건너뛴다."""
    if not TEST_REDIS_URL:
        pytest.skip(".env에 TEST_REDIS_URL이 없음")
    client = cache.connect(TEST_REDIS_URL)
    try:
        client.flushdb()  # 테스트 전용 DB 번호(1)만 비운다
    except cache.redis.RedisError:
        pytest.skip("테스트 Redis에 연결할 수 없음 (docker compose up -d 했는지 확인)")
    monkeypatch.setattr(cache, "client", client)
    return client


@pytest.fixture
def login_limit_redis(monkeypatch):
    """테스트 전용 Redis DB를 비우고 로그인 실패 제한에 끼운다. Redis가 꺼져 있으면 건너뛴다."""
    if not TEST_REDIS_URL:
        pytest.skip(".env에 TEST_REDIS_URL이 없음")
    client = cache.connect(TEST_REDIS_URL)
    try:
        client.flushdb()
    except cache.redis.RedisError:
        pytest.skip("테스트 Redis에 연결할 수 없음 (docker compose up -d 했는지 확인)")
    monkeypatch.setattr(login_limit, "client", client)
    return client
