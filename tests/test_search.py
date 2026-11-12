"""검색 API 테스트. 테스트 DB에 제품 몇 개를 넣고 /api/products를 호출한다."""

import pytest

from app.loader import save


def product(code, name, category, basis="100g", sodium=100):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": category,
            "basis": basis, "energy_kcal": 100, "sodium_mg": sodium, "sugar_g": 1, "sat_fat_g": 0}


@pytest.fixture
def client(engine, api):
    save(engine, [
        product("P1", "양조간장", "간장", basis="100ml", sodium=6000),
        product("P2", "진간장", "간장", basis="100ml", sodium=5500),
        product("P3", "국간장", "간장", basis="100g", sodium=7000),
        product("P4", "태양초 고추장", "고추장"),
        product("P5", "참치김밥", "김밥"),
        product("P6", "살코기 참치", "참치"),
        product("P7", "100% 사과주스", "과채주스"),
    ])
    return api


def names(response):
    return [item["name"] for item in response.json()["items"]]


def test_search_by_name_finds_part_of_name(client):
    response = client.get("/api/products", params={"q": "간장"})

    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert names(response) == ["국간장", "양조간장", "진간장"]  # 이름순


def test_category_filter_excludes_other_kinds(client):
    # 이름으로 찾으면 참치김밥도 섞이지만, 대표식품명으로 거르면 참치만 남는다
    assert sorted(names(client.get("/api/products", params={"q": "참치"}))) == ["살코기 참치", "참치김밥"]
    assert names(client.get("/api/products", params={"q": "참치", "category": "참치"})) == ["살코기 참치"]


def test_category_only_search(client):
    response = client.get("/api/products", params={"category": "간장"})

    assert response.json()["total"] == 3


def test_percent_sign_is_searched_as_a_letter(client):
    # %가 와일드카드로 쓰이면 모든 제품이 나온다
    assert names(client.get("/api/products", params={"q": "100%"})) == ["100% 사과주스"]


def test_pages_split_results_and_keep_total(client):
    first = client.get("/api/products", params={"category": "간장", "size": 2, "page": 1}).json()
    second = client.get("/api/products", params={"category": "간장", "size": 2, "page": 2}).json()

    assert first["total"] == second["total"] == 3
    assert [i["name"] for i in first["items"]] == ["국간장", "양조간장"]
    assert [i["name"] for i in second["items"]] == ["진간장"]


def test_result_includes_basis_and_nutrients(client):
    item = client.get("/api/products", params={"q": "양조간장"}).json()["items"][0]

    assert item["basis"] == "100ml"
    assert item["sodium_mg"] == 6000
    assert item["sat_fat_g"] == 0


def test_empty_search_is_rejected(client):
    assert client.get("/api/products").status_code == 400
    assert client.get("/api/products", params={"q": "   "}).status_code == 400


def filtered_client(engine, api):
    save(engine, [
        {"food_code": "S1", "name": "샘표 양조간장", "maker": "샘표식품", "category": "간장", "basis": "100ml",
         "energy_kcal": 60, "sodium_mg": 6000, "sugar_g": 1, "sat_fat_g": 0},
        {"food_code": "S2", "name": "저염 진간장", "maker": "샘표식품", "category": "간장", "basis": "100ml",
         "energy_kcal": 50, "sodium_mg": 3000, "sugar_g": 5, "sat_fat_g": 0},
        {"food_code": "S3", "name": "국간장", "maker": "샘표식품", "category": "간장", "basis": "100g",
         "energy_kcal": 40, "sodium_mg": 2000, "sugar_g": 0, "sat_fat_g": 0},
        {"food_code": "S4", "name": "정보없는간장", "maker": "샘표식품", "category": "간장", "basis": "100ml",
         "energy_kcal": None, "sodium_mg": None, "sugar_g": None, "sat_fat_g": None},
        {"food_code": "O1", "name": "샘표 아닌 간장", "maker": "다른회사", "category": "간장", "basis": "100ml",
         "energy_kcal": 70, "sodium_mg": 7000, "sugar_g": 2, "sat_fat_g": 0},
    ])
    return api


def test_search_by_maker(engine, api):
    client = filtered_client(engine, api)

    by_maker = names(client.get("/api/products", params={"q": "샘표", "target": "maker"}))
    by_name = names(client.get("/api/products", params={"q": "샘표"}))

    assert by_maker == ["국간장", "샘표 양조간장", "저염 진간장", "정보없는간장"]  # 회사 이름에 '샘표'
    assert by_name == ["샘표 아닌 간장", "샘표 양조간장"]  # 제품 이름에 '샘표'


def test_max_filters_keep_only_lower_or_equal(engine, api):
    client = filtered_client(engine, api)
    params = {"category": "간장", "basis": "100ml"}

    assert names(client.get("/api/products", params={**params, "max_sodium": 6000})) == ["샘표 양조간장", "저염 진간장"]
    assert names(client.get("/api/products", params={**params, "max_sodium": 6000, "max_sugar": 2})) == ["샘표 양조간장"]
    assert names(client.get("/api/products", params={**params, "max_kcal": 55})) == ["저염 진간장"]


def test_max_filter_excludes_unknown_values(engine, api):
    client = filtered_client(engine, api)

    # 정보없는간장은 값이 NULL이라 '이하'인지 알 수 없으므로 빠진다
    found = names(client.get("/api/products", params={"category": "간장", "max_sat_fat": 100}))

    assert "정보없는간장" not in found
    assert len(found) == 4


def test_basis_filter(engine, api):
    client = filtered_client(engine, api)

    assert names(client.get("/api/products", params={"category": "간장", "basis": "100g"})) == ["국간장"]


def test_invalid_search_options_are_rejected(client):
    assert client.get("/api/products", params={"q": "간장", "target": "category"}).status_code == 422
    assert client.get("/api/products", params={"q": "간장", "basis": "1kg"}).status_code == 422
    assert client.get("/api/products", params={"q": "간장", "max_sodium": -1}).status_code == 422


def test_page_size_is_limited(client):
    assert client.get("/api/products", params={"q": "간장", "size": 101}).status_code == 422
    assert client.get("/api/products", params={"q": "간장", "page": 0}).status_code == 422
