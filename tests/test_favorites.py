"""관심 제품 API 테스트 (v3 4단계): 저장, 목록, 삭제, 남의 데이터는 404."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.loader import save
from app.main import app

PASSWORD = "long-enough-password"


def product(code, name):
    return {"food_code": code, "name": name, "maker": "테스트식품", "category": "간장", "basis": "100ml",
            "energy_kcal": 60, "sodium_mg": 6000, "sugar_g": 1, "sat_fat_g": 0}


def bearer(api, email):
    """가입하고 로그인해서 Authorization 머리말을 돌려준다."""
    api.post("/api/auth/signup", json={"email": email, "password": PASSWORD})
    token = api.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def products(engine):
    save(engine, [product("P1", "양조간장"), product("P2", "저염간장"), product("P3", "국간장")])


@pytest.fixture
def me(api, products):
    return bearer(api, "me@example.com")


def saved_codes(api, headers):
    return [p["food_code"] for p in api.get("/api/me/favorites", headers=headers).json()]


def test_needs_login(api):
    assert api.get("/api/me/favorites").status_code == 401
    assert api.put("/api/me/favorites/P1").status_code == 401
    assert api.delete("/api/me/favorites/P1").status_code == 401


def test_save_and_list_newest_first(api, me):
    assert api.put("/api/me/favorites/P1", headers=me).status_code == 204
    assert api.put("/api/me/favorites/P2", headers=me).status_code == 204

    response = api.get("/api/me/favorites", headers=me)

    assert response.status_code == 200
    assert [p["food_code"] for p in response.json()] == ["P2", "P1"]  # 최근에 저장한 것 먼저
    assert response.json()[0]["name"] == "저염간장"  # 제품 정보가 같이 온다 (검색 결과와 같은 모양)


def test_saving_twice_keeps_one(api, me):
    api.put("/api/me/favorites/P1", headers=me)

    assert api.put("/api/me/favorites/P1", headers=me).status_code == 204  # 몇 번 해도 같은 결과
    assert saved_codes(api, me) == ["P1"]


def test_saving_unknown_product_is_404(api, me):
    response = api.put("/api/me/favorites/NO-SUCH", headers=me)

    assert response.status_code == 404
    assert saved_codes(api, me) == []


def test_delete(api, me):
    api.put("/api/me/favorites/P1", headers=me)
    api.put("/api/me/favorites/P2", headers=me)

    assert api.delete("/api/me/favorites/P1", headers=me).status_code == 204
    assert saved_codes(api, me) == ["P2"]
    assert api.delete("/api/me/favorites/P1", headers=me).status_code == 404  # 이미 지운 것


def test_lists_are_separate_and_others_data_is_404(api, me):
    other = bearer(api, "other@example.com")
    api.put("/api/me/favorites/P1", headers=other)

    # 다른 회원의 목록은 보이지 않고
    assert saved_codes(api, me) == []
    # 다른 회원이 저장한 제품을 내가 지우려 하면 '없는 것'과 똑같이 404 (403이면 그 데이터가 있다는 걸 알려 줌)
    response = api.delete("/api/me/favorites/P1", headers=me)
    assert response.status_code == 404
    assert response.json() == api.delete("/api/me/favorites/P3", headers=me).json()
    # 그 회원의 데이터는 그대로
    assert saved_codes(api, other) == ["P1"]


def test_deleting_user_or_product_deletes_favorites(engine, api, me):
    api.put("/api/me/favorites/P1", headers=me)
    api.put("/api/me/favorites/P2", headers=me)

    with engine.begin() as conn:
        conn.execute(text("DELETE FROM products WHERE food_code = 'P1'"))
        assert conn.execute(text("SELECT food_code FROM favorites")).scalars().all() == ["P2"]
        conn.execute(text("DELETE FROM users"))
        assert conn.execute(text("SELECT COUNT(*) FROM favorites")).scalar_one() == 0  # 외래 키 ON DELETE CASCADE


def test_reloading_products_keeps_favorites(engine, api, me):
    # 데이터를 다시 적재해도(ON DUPLICATE KEY UPDATE) 제품 행이 지워지지 않으므로 관심 제품이 남는다
    api.put("/api/me/favorites/P1", headers=me)

    save(engine, [product("P1", "양조간장(이름 바뀜)")])

    favorites = api.get("/api/me/favorites", headers=me).json()
    assert [(p["food_code"], p["name"]) for p in favorites] == [("P1", "양조간장(이름 바뀜)")]


def test_separate_client_cannot_use_cookie_on_api(api, me):
    # API는 쿠키를 보지 않는다: 화면에서 로그인한 브라우저라도 Bearer 토큰 없이는 401 (API는 CSRF 걱정이 없음)
    browser = TestClient(app)
    browser.post("/login", data={"email": "me@example.com", "password": PASSWORD})

    assert browser.cookies.get("access_token")
    assert browser.get("/api/me/favorites").status_code == 401
