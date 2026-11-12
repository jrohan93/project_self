"""v2 인덱스 테스트: 마이그레이션이 인덱스를 만들고, 비교·추천 쿼리가 그 인덱스를 쓰는지 확인한다."""

from sqlalchemy import inspect, text

from app.loader import save
from app.models import Product


def test_migration_creates_category_basis_indexes(engine):
    indexes = {ix["name"]: ix["column_names"] for ix in inspect(engine).get_indexes("products")}

    assert indexes["ix_products_category_basis_sodium"] == ["category", "basis", "sodium_mg"]
    assert indexes["ix_products_category_basis_sugar"] == ["category", "basis", "sugar_g"]
    assert indexes["ix_products_category_basis_sat_fat"] == ["category", "basis", "sat_fat_g"]


def test_model_declares_same_indexes_as_migration(engine):
    # 모델(models.py)과 실제 DB(alembic 0002)가 어긋나지 않게
    in_db = {ix["name"] for ix in inspect(engine).get_indexes("products")}
    in_model = {ix.name for ix in Product.__table__.indexes}

    assert in_model == in_db


def test_compare_query_reads_only_one_group(engine):
    # 다른 종류가 많아도 (대표식품명, 기준량) 묶음만 읽어야 한다 (전체 읽기 = type ALL)
    rows = [{"food_code": f"O{i:04}", "name": f"다른{i}", "maker": None, "category": f"기타{i % 50}",
             "basis": "100g", "energy_kcal": 1, "sodium_mg": i, "sugar_g": 1, "sat_fat_g": 1} for i in range(2000)]
    rows += [{"food_code": f"S{i}", "name": f"간장{i}", "maker": None, "category": "간장",
              "basis": "100ml", "energy_kcal": 1, "sodium_mg": 5000 + i, "sugar_g": 1, "sat_fat_g": 1} for i in range(5)]
    save(engine, rows)

    with engine.connect() as conn:
        conn.execute(text("ANALYZE TABLE products"))  # 행 수 통계를 새로 고쳐야 옵티마이저가 인덱스를 고른다
        plan = conn.execute(text(
            "EXPLAIN SELECT * FROM products WHERE category = '간장' AND basis = '100ml' "
            "AND sodium_mg < 5003 ORDER BY sodium_mg LIMIT 5"
        )).mappings().one()

    assert plan["type"] != "ALL"
    assert plan["key"].startswith("ix_products_category_basis_")
