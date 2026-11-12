"""제품 상세 API 테스트 (/api/products/{식품코드})."""

from app.loader import save


def test_detail_shows_basis_and_nutrients(engine, api):
    save(engine, [{"food_code": "P101-1", "name": "양조간장", "maker": "샘표", "category": "간장",
                   "basis": "100ml", "energy_kcal": 60, "sodium_mg": 6000, "sugar_g": 1.5, "sat_fat_g": 0}])

    response = api.get("/api/products/P101-1")

    assert response.status_code == 200
    assert response.json() == {
        "food_code": "P101-1", "name": "양조간장", "maker": "샘표", "category": "간장",
        "basis": "100ml", "energy_kcal": 60.0, "sodium_mg": 6000.0, "sugar_g": 1.5, "sat_fat_g": 0.0,
    }


def test_missing_values_are_null_not_zero(engine, api):
    # 정보 없음(null)과 실제 0(sat_fat_g)이 구분되어야 한다
    save(engine, [{"food_code": "P107-1", "name": "참기름", "maker": None, "category": "참기름",
                   "basis": "100g", "energy_kcal": 900, "sodium_mg": None, "sugar_g": 0, "sat_fat_g": 14}])

    item = api.get("/api/products/P107-1").json()

    assert item["sodium_mg"] is None
    assert item["maker"] is None
    assert item["sugar_g"] == 0


def test_unknown_food_code_is_404(api):
    response = api.get("/api/products/NO-SUCH-CODE")

    assert response.status_code == 404
