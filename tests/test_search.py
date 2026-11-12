"""검색 API 테스트. 테스트 DB에 제품 몇 개를 넣고 /api/products를 호출한다."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.loader import save
from app.main import app, get_session


def product(code, name, category, basis="100g", sodium=100):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": category,
            "basis": basis, "energy_kcal": 100, "sodium_mg": sodium, "sugar_g": 1, "sat_fat_g": 0}


@pytest.fixture
def client(engine):
    save(engine, [
        product("P1", "양조간장", "간장", basis="100ml", sodium=6000),
        product("P2", "진간장", "간장", basis="100ml", sodium=5500),
        product("P3", "국간장", "간장", basis="100g", sodium=7000),
        product("P4", "태양초 고추장", "고추장"),
        product("P5", "참치김밥", "김밥"),
        product("P6", "살코기 참치", "참치"),
        product("P7", "100% 사과주스", "과채주스"),
    ])

    # 앱이 실제 DB 대신 테스트 DB를 쓰도록 세션을 바꿔 끼운다
    TestSession = sessionmaker(engine)

    def test_session():
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_session] = test_session
    yield TestClient(app)
    app.dependency_overrides.clear()


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


def test_page_size_is_limited(client):
    assert client.get("/api/products", params={"q": "간장", "size": 101}).status_code == 422
    assert client.get("/api/products", params={"q": "간장", "page": 0}).status_code == 422
