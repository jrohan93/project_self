"""여러 테스트 파일이 같이 쓰는 준비물.

engine: 테스트 전용 DB(TEST_DATABASE_URL)에 빈 products 테이블을 만들어 준다.
        마이그레이션은 테스트 실행마다 한 번만 처음부터 다시 적용하고(FULLTEXT 인덱스 만들기가 느려서),
        테스트마다 TRUNCATE로 테이블만 비운다.
api: 그 테스트 DB를 쓰는 FastAPI TestClient.
MySQL이 떠 있지 않으면 그 테스트는 건너뛴다 (docker compose up -d 후 실행).
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.main import app, get_session

load_dotenv()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


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
    """테스트마다: 테이블을 비워서 빈 테이블로 시작한다 (인덱스는 그대로)."""
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE products"))
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
