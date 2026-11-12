"""대체 제품 추천 API 테스트 (/api/products/{식품코드}/alternatives)."""

import pytest

from app.loader import save


def product(code, name, category="간장", basis="100ml", sodium=6000, sugar=1):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": category,
            "basis": basis, "energy_kcal": 60, "sodium_mg": sodium, "sugar_g": sugar, "sat_fat_g": 0}


@pytest.fixture
def client(engine, api):
    save(engine, [
        product("BASE", "기준간장", sodium=6000, sugar=3),
        product("P1", "저염간장", sodium=3000, sugar=5),
        product("P2", "덜짠간장", sodium=4500, sugar=1),
        product("P3", "같은간장", sodium=6000, sugar=2),          # 같은 값은 '더 낮음'이 아님
        product("P4", "짠간장", sodium=7000, sugar=0),
        product("P5", "정보없는간장", sodium=None, sugar=None),  # 정보 없음은 후보에서 제외
        product("P6", "국간장", basis="100g", sodium=100),        # 기준량이 다름
        product("P7", "태양초 고추장", category="고추장", sodium=10),  # 종류가 다름
        product("NULLBASE", "나트륨모름간장", sodium=None, sugar=10),
    ])
    return api


def names(response):
    return [item["name"] for item in response.json()["items"]]


def test_recommends_lower_sodium_in_same_category_and_basis(client):
    response = client.get("/api/products/BASE/alternatives", params={"by": "sodium"})

    assert response.status_code == 200
    body = response.json()
    # 낮은 순. 같은 값(같은간장)·더 높은 값(짠간장)·정보 없음·다른 기준량·다른 종류는 빠짐
    assert names(response) == ["저염간장", "덜짠간장"]
    assert body["total"] == 2
    assert body["by"] == "sodium"
    assert body["product"]["food_code"] == "BASE"


def test_recommends_lower_sugar_without_more_sodium(client):
    response = client.get("/api/products/BASE/alternatives", params={"by": "sugar"})

    # 당류 3보다 낮은 것: 짠간장 0, 덜짠간장 1, 같은간장 2
    # 짠간장은 나트륨이 7000 > 6000이라 빠지고, 같은간장은 나트륨이 같아서 남는다
    assert names(response) == ["덜짠간장", "같은간장"]


def test_sugar_search_excludes_unknown_sodium(engine, api):
    save(engine, [
        product("BASE", "기준간장", sodium=6000, sugar=3),
        product("P1", "나트륨모름간장", sodium=None, sugar=1),  # 더 짜지 않다고 말할 수 없음
    ])

    assert names(api.get("/api/products/BASE/alternatives", params={"by": "sugar"})) == []


def test_sugar_search_without_base_sodium_skips_sodium_check(client):
    # 기준 제품의 나트륨이 정보 없음이면 나트륨 조건 없이 당류만 본다 (당류 10보다 낮은 5개)
    body = client.get("/api/products/NULLBASE/alternatives", params={"by": "sugar"}).json()

    assert body["total"] == 5


def test_no_alternatives_when_base_value_is_unknown(client):
    # 기준 제품의 나트륨이 정보 없음이면 더 낮다고 말할 수 없다
    body = client.get("/api/products/NULLBASE/alternatives", params={"by": "sodium"}).json()

    assert body["total"] == 0
    assert body["items"] == []
    assert body["product"]["sodium_mg"] is None


def test_lowest_product_has_no_alternatives(client):
    body = client.get("/api/products/P1/alternatives", params={"by": "sodium"}).json()

    assert body["total"] == 0


def test_limit_keeps_total(client):
    body = client.get("/api/products/BASE/alternatives", params={"by": "sugar", "limit": 1}).json()

    assert body["total"] == 2
    assert [item["name"] for item in body["items"]] == ["덜짠간장"]


def test_unknown_product_is_404(client):
    assert client.get("/api/products/NO-SUCH-CODE/alternatives").status_code == 404


def test_invalid_inputs_are_rejected(client):
    assert client.get("/api/products/BASE/alternatives", params={"by": "sat_fat"}).status_code == 422
    assert client.get("/api/products/BASE/alternatives", params={"limit": 0}).status_code == 422
    assert client.get("/api/products/BASE/alternatives", params={"limit": 51}).status_code == 422
