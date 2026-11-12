"""MySQL에 실제로 저장하는 테스트. engine 준비물은 conftest.py에 있다."""

from sqlalchemy import func, select

from app.loader import save
from app.models import Product


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
