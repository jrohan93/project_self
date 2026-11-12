"""같은 종류 비교 API 테스트 (/api/compare)."""

import pytest

from app.loader import save


def product(code, name, category="간장", basis="100ml", sodium=6000, sugar=1, sat_fat=0):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": category,
            "basis": basis, "energy_kcal": 60, "sodium_mg": sodium, "sugar_g": sugar, "sat_fat_g": sat_fat}


@pytest.fixture
def client(engine, api):
    save(engine, [
        product("P1", "양조간장", sodium=6000, sugar=3),
        product("P2", "저염간장", sodium=3000, sugar=5),
        product("P3", "진간장", sodium=5500, sugar=None),
        product("P4", "정보없는간장", sodium=None, sugar=1),
        product("P5", "국간장", basis="100g", sodium=100),       # 기준량이 다름
        product("P6", "태양초 고추장", category="고추장", sodium=10),  # 종류가 다름
    ])
    return api


def names(response):
    return [item["name"] for item in response.json()["items"]]


def test_compares_only_same_category_and_basis(client):
    response = client.get("/api/compare", params={"category": "간장", "basis": "100ml"})

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    assert "국간장" not in names(response)        # 100g이라 제외
    assert "태양초 고추장" not in names(response)  # 고추장이라 제외
    assert (body["category"], body["basis"], body["sort"]) == ("간장", "100ml", "sodium")


def test_sorted_by_sodium_low_first_and_null_last(client):
    response = client.get("/api/compare", params={"category": "간장", "basis": "100ml", "sort": "sodium"})

    # 정보 없는 제품은 0이 아니므로 맨 앞이 아니라 맨 뒤
    assert names(response) == ["저염간장", "진간장", "양조간장", "정보없는간장"]


def test_sorted_by_sugar(client):
    response = client.get("/api/compare", params={"category": "간장", "basis": "100ml", "sort": "sugar"})

    assert names(response) == ["정보없는간장", "양조간장", "저염간장", "진간장"]


def test_same_value_is_ordered_by_name(engine, api):
    save(engine, [product("A", "나간장", sodium=5000), product("B", "가간장", sodium=5000)])

    response = api.get("/api/compare", params={"category": "간장", "basis": "100ml"})

    assert names(response) == ["가간장", "나간장"]


def test_null_stays_last_across_pages(client):
    params = {"category": "간장", "basis": "100ml", "size": 3}
    first = client.get("/api/compare", params={**params, "page": 1})
    second = client.get("/api/compare", params={**params, "page": 2})

    assert names(first) == ["저염간장", "진간장", "양조간장"]
    assert names(second) == ["정보없는간장"]


def test_invalid_inputs_are_rejected(client):
    assert client.get("/api/compare", params={"basis": "100ml"}).status_code == 422  # 대표식품명 없음
    assert client.get("/api/compare", params={"category": "간장"}).status_code == 422  # 기준량 없음
    assert client.get("/api/compare", params={"category": "간장", "basis": "1kg"}).status_code == 422
    assert client.get("/api/compare", params={"category": "간장", "basis": "100ml", "sort": "energy"}).status_code == 422
