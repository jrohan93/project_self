"""여러 테스트 파일이 같이 쓰는 준비물.

engine: 테스트 전용 DB(TEST_DATABASE_URL)에 빈 products 테이블을 만들어 준다.
MySQL이 떠 있지 않으면 그 테스트는 건너뛴다 (docker compose up -d 후 실행).
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

load_dotenv()
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture
def engine():
    if not TEST_DATABASE_URL:
        pytest.skip(".env에 TEST_DATABASE_URL이 없음")
    engine = create_engine(TEST_DATABASE_URL)
    try:
        engine.connect().close()
    except OperationalError:
        pytest.skip("테스트 DB에 연결할 수 없음 (docker compose up -d 했는지 확인)")

    # 마이그레이션을 처음부터 다시 적용해서 빈 테이블로 시작한다
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    yield engine
    engine.dispose()
