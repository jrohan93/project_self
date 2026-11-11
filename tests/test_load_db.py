"""MySQL에 실제로 저장하는 테스트. 테스트 전용 DB(TEST_DATABASE_URL)를 쓴다.

MySQL이 떠 있지 않으면 건너뛴다 (docker compose up -d 후 실행).
"""

import os

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError

from app.loader import save
from app.models import Product

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


def record(code, sodium):
    return {"food_code": code, "name": "양조간장", "maker": "샘표", "category": "간장",
            "basis": "100ml", "energy_kcal": 60, "sodium_mg": sodium, "sugar_g": 1, "sat_fat_g": None}


def test_running_twice_does_not_create_duplicates(engine):
    save(engine, [record("A", 6000), record("B", 5000)])
    save(engine, [record("A", 5500), record("B", 5000)])  # 같은 식품코드로 다시 적재

    with engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(Product)) == 2
        # 다시 적재하면 새 값으로 바뀐다
        assert conn.scalar(select(Product.sodium_mg).where(Product.food_code == "A")) == 5500


def test_blank_value_is_stored_as_null(engine):
    save(engine, [record("A", None)])

    with engine.connect() as conn:
        row = conn.execute(select(Product).where(Product.food_code == "A")).one()
    assert row.sodium_mg is None
    assert row.sat_fat_g is None
